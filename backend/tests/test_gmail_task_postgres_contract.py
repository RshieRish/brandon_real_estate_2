from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.gmail_task_postgres import (
    OWNERSHIP_MARKER_TABLE,
    cleanup_owned_schema,
    gmail_task_test_url,
    public_schema_user_objects,
    run_alembic,
    sync_test_url,
)


CRM_MARKER_TABLE = "_crm_task_lifecycle_test_ownership"


def _engine() -> tuple[sa.Engine, str]:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    return sa.create_engine(sync_test_url(url)), expected_database


def _require_exact_database(
    connection: sa.Connection,
    expected_database: str,
) -> None:
    actual_database = connection.scalar(sa.text("SELECT current_database()"))
    if actual_database != expected_database:
        pytest.fail("test fixture is not connected to the exact test database")


def _optimized_gmail_helper(
    *,
    mode: str,
    expected_database: str,
    marker: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    code = """
import sys
import sqlalchemy as sa
from tests.gmail_task_postgres import (
    cleanup_owned_schema,
    gmail_task_test_url,
    owned_empty_test_schema,
    sync_test_url,
)
mode, expected_database, marker = sys.argv[1:]
url = gmail_task_test_url()
engine = sa.create_engine(sync_test_url(url))
try:
    if mode == "cleanup":
        with engine.begin() as connection:
            cleanup_owned_schema(
                connection,
                expected_database=expected_database,
                run_marker=marker,
            )
    elif mode == "claim":
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            pass
    elif mode == "downgrade":
        from tests.gmail_task_postgres import run_owned_alembic_downgrade
        run_owned_alembic_downgrade(
            url,
            "base",
            expected_database=expected_database,
            run_marker=marker,
        )
    else:
        raise RuntimeError("unsupported test mode")
finally:
    engine.dispose()
"""
    return subprocess.run(
        [sys.executable, "-O", "-c", code, mode, expected_database, marker],
        cwd=Path(__file__).parents[1],
        env=environment or os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _optimized_crm_helper(
    *,
    mode: str,
    expected_database: str,
    marker: str,
) -> subprocess.CompletedProcess[str]:
    code = """
import importlib.util
import pathlib
import sys
import sqlalchemy as sa
test_path = pathlib.Path("tests/test_crm_task_lifecycle_migration.py")
spec = importlib.util.spec_from_file_location("crm_revision_81_contract", test_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
mode, expected_database, marker = sys.argv[1:]
url = module._isolated_test_url()
engine = sa.create_engine(module._sync_test_url(url))
try:
    if mode == "cleanup":
        with engine.begin() as connection:
            module._cleanup_owned_test_schema(
                connection,
                expected_database=expected_database,
                ownership_marker=marker,
            )
    elif mode == "claim":
        with module._owned_empty_test_schema(engine, expected_database):
            pass
    else:
        raise RuntimeError("unsupported test mode")
finally:
    engine.dispose()
"""
    environment = os.environ.copy()
    environment["CRM_TASK_TEST_DATABASE_NAME"] = os.environ[
        "GMAIL_TASK_TEST_DATABASE_NAME"
    ]
    environment["CRM_TASK_TEST_DATABASE_URL"] = os.environ[
        "GMAIL_TASK_TEST_DATABASE_URL"
    ]
    return subprocess.run(
        [sys.executable, "-O", "-c", code, mode, expected_database, marker],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _prepare_marker_case(
    connection: sa.Connection,
    *,
    table_name: str,
    marker_column: str,
    rows: tuple[str, ...] | None,
    sentinel: str,
) -> None:
    connection.exec_driver_sql(
        f"CREATE TABLE public.{sentinel} (value text NOT NULL)"
    )
    connection.execute(
        sa.text(f"INSERT INTO public.{sentinel} (value) VALUES ('preserve-me')")
    )
    if rows is None:
        return
    connection.exec_driver_sql(
        f"CREATE TABLE public.{table_name} ({marker_column} text NOT NULL)"
    )
    for row in rows:
        connection.execute(
            sa.text(
                f"INSERT INTO public.{table_name} ({marker_column}) "
                "VALUES (:marker)"
            ),
            {"marker": row},
        )


def _resolved_marker_rows(
    rows: tuple[str, ...] | None,
    marker: str,
) -> tuple[str, ...] | None:
    if rows is None:
        return None
    return tuple(marker if row == "expected" else row for row in rows)


def _restore_exact_gmail_marker_and_cleanup(
    engine: sa.Engine,
    *,
    expected_database: str,
    marker: str,
) -> None:
    with engine.begin() as connection:
        _require_exact_database(connection, expected_database)
        connection.exec_driver_sql(
            f"DROP TABLE IF EXISTS public.{OWNERSHIP_MARKER_TABLE}"
        )
        connection.exec_driver_sql(
            f"CREATE TABLE public.{OWNERSHIP_MARKER_TABLE} "
            "(run_marker text PRIMARY KEY)"
        )
        connection.execute(
            sa.text(
                f"INSERT INTO public.{OWNERSHIP_MARKER_TABLE} (run_marker) "
                "VALUES (:marker)"
            ),
            {"marker": marker},
        )
    with engine.begin() as connection:
        cleanup_owned_schema(
            connection,
            expected_database=expected_database,
            run_marker=marker,
        )


def _restore_exact_crm_marker_and_cleanup(
    engine: sa.Engine,
    *,
    expected_database: str,
    marker: str,
) -> None:
    with engine.begin() as connection:
        _require_exact_database(connection, expected_database)
        connection.exec_driver_sql(
            f"DROP TABLE IF EXISTS public.{CRM_MARKER_TABLE}"
        )
        connection.exec_driver_sql(
            f"CREATE TABLE public.{CRM_MARKER_TABLE} "
            "(marker text PRIMARY KEY)"
        )
        connection.execute(
            sa.text(
                f"INSERT INTO public.{CRM_MARKER_TABLE} (marker) "
                "VALUES (:marker)"
            ),
            {"marker": marker},
        )

    test_path = Path(__file__).parent / "test_crm_task_lifecycle_migration.py"
    spec = __import__("importlib.util").util.spec_from_file_location(
        "crm_revision_81_cleanup", test_path
    )
    if spec is None or spec.loader is None:
        pytest.fail("unable to load revision-81 contract helper")
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module._cleanup_owned_test_schema(
            connection,
            expected_database=expected_database,
            ownership_marker=marker,
        )


def test_ci_requires_both_gmail_postgresql_settings(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("GMAIL_TASK_TEST_DATABASE_NAME", raising=False)
    monkeypatch.delenv("GMAIL_TASK_TEST_DATABASE_URL", raising=False)

    with pytest.raises(BaseException, match="CI requires GMAIL_TASK_TEST"):
        gmail_task_test_url()


@pytest.mark.parametrize(
    ("database_name", "database_url", "message"),
    (
        (
            "gmail_contract",
            "postgresql+asyncpg://fixture@localhost/gmail_contract",
            "must end in _test",
        ),
        (
            "configured_test",
            "postgresql+asyncpg://fixture@localhost/different_test",
            "exact configured database",
        ),
        (
            "configured_test",
            "sqlite+aiosqlite:///configured_test",
            "require PostgreSQL",
        ),
    ),
)
def test_url_guards_survive_python_optimization(
    database_name: str,
    database_url: str,
    message: str,
) -> None:
    environment = os.environ.copy()
    environment["CI"] = "false"
    environment["GMAIL_TASK_TEST_DATABASE_NAME"] = database_name
    environment["GMAIL_TASK_TEST_DATABASE_URL"] = database_url
    completed = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "from tests.gmail_task_postgres import gmail_task_test_url; "
            "gmail_task_test_url()",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode != 0
    assert message in f"{completed.stdout}\n{completed.stderr}"


def test_unowned_alembic_downgrade_refuses_before_subprocess(
    monkeypatch,
) -> None:
    subprocess_called = False

    def unexpected_subprocess(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("subprocess reached")

    monkeypatch.setattr(
        "tests.gmail_task_postgres.subprocess.run",
        unexpected_subprocess,
    )
    with pytest.raises(BaseException, match="ownership-aware"):
        run_alembic(
            make_url(
                "postgresql+asyncpg://fixture@localhost/safe_test"
            ),
            "downgrade",
            "base",
        )
    assert subprocess_called is False


@pytest.mark.parametrize(
    ("rows", "expected_fragment"),
    (
        (None, "ownership marker table"),
        (("expected", "expected"), "exact ownership marker tuple"),
        (("foreign",), "exact ownership marker tuple"),
    ),
)
def test_gmail_cleanup_marker_guards_survive_python_optimization_and_preserve_sentinel(
    rows: tuple[str, ...] | None,
    expected_fragment: str,
) -> None:
    engine, expected_database = _engine()
    marker = uuid4().hex
    sentinel = f"_gmail_guard_evidence_{uuid4().hex[:12]}"
    ownership_armed = False
    try:
        with engine.begin() as connection:
            _require_exact_database(connection, expected_database)
            if public_schema_user_objects(connection):
                pytest.fail("Gmail helper contract requires an empty schema")
            _prepare_marker_case(
                connection,
                table_name=OWNERSHIP_MARKER_TABLE,
                marker_column="run_marker",
                rows=_resolved_marker_rows(rows, marker),
                sentinel=sentinel,
            )
        ownership_armed = True

        completed = _optimized_gmail_helper(
            mode="cleanup",
            expected_database=expected_database,
            marker=marker,
        )
        assert completed.returncode != 0
        assert expected_fragment in f"{completed.stdout}\n{completed.stderr}"
        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM public.{sentinel}")
            ) == "preserve-me"
    finally:
        if ownership_armed:
            _restore_exact_gmail_marker_and_cleanup(
                engine,
                expected_database=expected_database,
                marker=marker,
            )
        engine.dispose()


@pytest.mark.parametrize(
    ("rows", "expected_fragment"),
    (
        (None, "ownership marker table"),
        (("expected", "expected"), "exact ownership marker tuple"),
        (("foreign",), "exact ownership marker tuple"),
    ),
)
def test_gmail_downgrade_marker_guards_survive_python_optimization_and_preserve_sentinel(
    rows: tuple[str, ...] | None,
    expected_fragment: str,
) -> None:
    engine, expected_database = _engine()
    marker = uuid4().hex
    sentinel = f"_gmail_downgrade_evidence_{uuid4().hex[:12]}"
    ownership_armed = False
    try:
        with engine.begin() as connection:
            _require_exact_database(connection, expected_database)
            if public_schema_user_objects(connection):
                pytest.fail("Gmail downgrade contract requires an empty schema")
            _prepare_marker_case(
                connection,
                table_name=OWNERSHIP_MARKER_TABLE,
                marker_column="run_marker",
                rows=_resolved_marker_rows(rows, marker),
                sentinel=sentinel,
            )
        ownership_armed = True

        completed = _optimized_gmail_helper(
            mode="downgrade",
            expected_database=expected_database,
            marker=marker,
        )
        assert completed.returncode != 0
        assert expected_fragment in f"{completed.stdout}\n{completed.stderr}"
        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM public.{sentinel}")
            ) == "preserve-me"
    finally:
        if ownership_armed:
            _restore_exact_gmail_marker_and_cleanup(
                engine,
                expected_database=expected_database,
                marker=marker,
            )
        engine.dispose()


def test_gmail_wrong_database_and_populated_claim_survive_python_optimization() -> None:
    engine, expected_database = _engine()
    marker = uuid4().hex
    sentinel = f"_gmail_guard_evidence_{uuid4().hex[:12]}"
    ownership_armed = False
    try:
        with engine.begin() as connection:
            _require_exact_database(connection, expected_database)
            if public_schema_user_objects(connection):
                pytest.fail("Gmail helper contract requires an empty schema")
            _prepare_marker_case(
                connection,
                table_name=OWNERSHIP_MARKER_TABLE,
                marker_column="run_marker",
                rows=(marker,),
                sentinel=sentinel,
            )
        ownership_armed = True

        wrong_database = _optimized_gmail_helper(
            mode="cleanup",
            expected_database="other_exact_test",
            marker=marker,
        )
        assert wrong_database.returncode != 0
        assert "exact configured test database" in (
            wrong_database.stdout + wrong_database.stderr
        )

        populated = _optimized_gmail_helper(
            mode="claim",
            expected_database=expected_database,
            marker=marker,
        )
        assert populated.returncode != 0
        assert "public schema is not empty" in (
            populated.stdout + populated.stderr
        )
        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM public.{sentinel}")
            ) == "preserve-me"
    finally:
        if ownership_armed:
            _restore_exact_gmail_marker_and_cleanup(
                engine,
                expected_database=expected_database,
                marker=marker,
            )
        engine.dispose()


def test_unexpected_preexisting_object_is_never_claimed_or_broadly_cleaned() -> None:
    from tests.gmail_task_postgres import owned_empty_test_schema

    engine, expected_database = _engine()
    sentinel = f"_unexpected_preexisting_{uuid4().hex[:12]}"
    sentinel_created = False
    try:
        with engine.begin() as connection:
            _require_exact_database(connection, expected_database)
            if public_schema_user_objects(connection):
                pytest.fail("precondition regression requires an empty schema")
            connection.exec_driver_sql(
                f"CREATE TABLE public.{sentinel} (value text NOT NULL)"
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO public.{sentinel} (value) "
                    "VALUES ('preserve-me')"
                )
            )
            sentinel_created = True

        with pytest.raises(BaseException, match="public schema is not empty"):
            with owned_empty_test_schema(
                engine,
                expected_database=expected_database,
            ):
                pytest.fail("an unexpected populated schema must not be claimed")

        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM public.{sentinel}")
            ) == "preserve-me"
            assert connection.scalar(
                sa.text("SELECT to_regclass(:marker_table)") ,
                {"marker_table": f"public.{OWNERSHIP_MARKER_TABLE}"},
            ) is None
    finally:
        if sentinel_created:
            with engine.begin() as connection:
                _require_exact_database(connection, expected_database)
                connection.exec_driver_sql(f"DROP TABLE public.{sentinel}")
        engine.dispose()


@pytest.mark.parametrize(
    ("mode", "rows", "expected_database_override", "expected_fragment"),
    (
        ("cleanup", None, None, "ownership marker table"),
        ("cleanup", ("expected", "expected"), None, "exact test ownership marker"),
        ("cleanup", ("foreign",), None, "exact test ownership marker"),
        ("cleanup", ("expected",), "other_exact_test", "exact configured test database"),
        ("claim", None, None, "public schema is not empty"),
    ),
)
def test_revision_81_guards_survive_python_optimization_and_preserve_sentinel(
    mode: str,
    rows: tuple[str, ...] | None,
    expected_database_override: str | None,
    expected_fragment: str,
) -> None:
    engine, expected_database = _engine()
    marker = uuid4().hex
    sentinel = f"_crm_guard_evidence_{uuid4().hex[:12]}"
    ownership_armed = False
    try:
        with engine.begin() as connection:
            _require_exact_database(connection, expected_database)
            if public_schema_user_objects(connection):
                pytest.fail("revision-81 guard contract requires an empty schema")
            _prepare_marker_case(
                connection,
                table_name=CRM_MARKER_TABLE,
                marker_column="marker",
                rows=_resolved_marker_rows(rows, marker),
                sentinel=sentinel,
            )
        ownership_armed = True

        completed = _optimized_crm_helper(
            mode=mode,
            expected_database=expected_database_override or expected_database,
            marker=marker,
        )
        assert completed.returncode != 0
        assert expected_fragment in f"{completed.stdout}\n{completed.stderr}"
        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM public.{sentinel}")
            ) == "preserve-me"
    finally:
        if ownership_armed:
            _restore_exact_crm_marker_and_cleanup(
                engine,
                expected_database=expected_database,
                marker=marker,
            )
        engine.dispose()
