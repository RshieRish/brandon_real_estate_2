from __future__ import annotations

import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url


OWNERSHIP_MARKER_TABLE = "_gmail_sydney_test_ownership"


def fail_closed(message: str) -> None:
    if os.getenv("CI", "").strip().lower() == "true":
        pytest.fail(message)
    raise RuntimeError(message)


def gmail_task_test_url() -> URL:
    raw_url = os.getenv("GMAIL_TASK_TEST_DATABASE_URL")
    expected_database = os.getenv("GMAIL_TASK_TEST_DATABASE_NAME")
    if not raw_url or not expected_database:
        if os.getenv("CI", "").strip().lower() == "true":
            pytest.fail(
                "CI requires GMAIL_TASK_TEST_DATABASE_NAME and "
                "GMAIL_TASK_TEST_DATABASE_URL"
            )
        pytest.skip("GMAIL_TASK_TEST_DATABASE_URL is not provisioned")

    url = make_url(raw_url)
    if not expected_database.endswith("_test"):
        fail_closed("GMAIL_TASK_TEST_DATABASE_NAME must end in _test")
    if url.database != expected_database:
        fail_closed(
            "GMAIL_TASK_TEST_DATABASE_URL must target the exact configured "
            "database"
        )
    if not (url.database or "").endswith("_test"):
        fail_closed("GMAIL_TASK_TEST_DATABASE_URL must target a _test database")
    if not url.drivername.startswith("postgresql"):
        fail_closed("Gmail/Sydney persistence tests require PostgreSQL")
    return url


def sync_test_url(url: URL) -> URL:
    query = dict(url.query)
    async_ssl_mode = query.pop("ssl", None)
    if async_ssl_mode is not None:
        query.setdefault("sslmode", async_ssl_mode)
    return url.set(drivername="postgresql+psycopg2", query=query)


def async_test_url(url: URL) -> URL:
    query = dict(url.query)
    sync_ssl_mode = query.pop("sslmode", None)
    if sync_ssl_mode is not None:
        query.setdefault("ssl", sync_ssl_mode)
    return url.set(drivername="postgresql+asyncpg", query=query)


def _run_alembic_command(url: URL, *arguments: str) -> str:
    backend_root = Path(__file__).parents[1]
    alembic_executable = Path(sys.executable).with_name("alembic")
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    environment.setdefault("JWT_SECRET", "test-secret")
    completed = subprocess.run(
        [str(alembic_executable), *arguments],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(arguments)} failed with exit code "
            f"{completed.returncode}:\n{output}"
        )
    return output


def run_alembic(url: URL, *arguments: str) -> str:
    if "downgrade" in arguments:
        fail_closed(
            "Alembic downgrade requires the ownership-aware downgrade helper"
        )
    return _run_alembic_command(url, *arguments)


def public_schema_user_objects(connection: sa.Connection) -> list[str]:
    return list(
        connection.scalars(
            sa.text(
                """
                SELECT object_name
                FROM (
                    SELECT 'relation:' || c.relname AS object_name
                    FROM pg_catalog.pg_class AS c
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c', 'i', 'I')
                    UNION ALL
                    SELECT 'routine:' || p.proname
                    FROM pg_catalog.pg_proc AS p
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'type:' || t.typname
                    FROM pg_catalog.pg_type AS t
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'public' AND t.typrelid = 0
                    UNION ALL
                    SELECT 'extension:' || e.extname
                    FROM pg_catalog.pg_extension AS e
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'collation:' || c.collname
                    FROM pg_catalog.pg_collation AS c
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.collnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'conversion:' || c.conname
                    FROM pg_catalog.pg_conversion AS c
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.connamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator:' || o.oprname
                    FROM pg_catalog.pg_operator AS o
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = o.oprnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator_class:' || o.opcname
                    FROM pg_catalog.pg_opclass AS o
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = o.opcnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator_family:' || o.opfname
                    FROM pg_catalog.pg_opfamily AS o
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = o.opfnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_config:' || c.cfgname
                    FROM pg_catalog.pg_ts_config AS c
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.cfgnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_dictionary:' || d.dictname
                    FROM pg_catalog.pg_ts_dict AS d
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = d.dictnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_parser:' || p.prsname
                    FROM pg_catalog.pg_ts_parser AS p
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.prsnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_template:' || t.tmplname
                    FROM pg_catalog.pg_ts_template AS t
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = t.tmplnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'extended_statistic:' || s.stxname
                    FROM pg_catalog.pg_statistic_ext AS s
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = s.stxnamespace
                    WHERE n.nspname = 'public'
                ) AS public_objects
                ORDER BY object_name
                """
            )
        )
    )


def verify_exact_ownership(
    connection: sa.Connection,
    *,
    expected_database: str,
    run_marker: str,
) -> None:
    actual_database = connection.scalar(sa.text("SELECT current_database()"))
    if actual_database != expected_database:
        fail_closed("refusing cleanup outside the exact configured test database")

    marker_oid = connection.scalar(
        sa.text("SELECT to_regclass(:table_name)::oid"),
        {"table_name": f"public.{OWNERSHIP_MARKER_TABLE}"},
    )
    if marker_oid is None:
        fail_closed("refusing cleanup without the ownership marker table")

    marker_counts = tuple(
        connection.execute(
            sa.text(
                f"SELECT count(*), count(*) FILTER (WHERE run_marker = :marker) "
                f"FROM public.{OWNERSHIP_MARKER_TABLE}"
            ),
            {"marker": run_marker},
        ).one()
    )
    if marker_counts != (1, 1):
        fail_closed("refusing cleanup without the exact ownership marker tuple")


def run_owned_alembic_downgrade(
    url: URL,
    revision: str,
    *,
    expected_database: str,
    run_marker: str,
) -> str:
    configured_url = gmail_task_test_url()
    if url != configured_url or expected_database != configured_url.database:
        fail_closed(
            "refusing downgrade outside the exact configured test database"
        )
    engine = sa.create_engine(sync_test_url(url))
    try:
        with engine.connect() as connection:
            verify_exact_ownership(
                connection,
                expected_database=expected_database,
                run_marker=run_marker,
            )
    finally:
        engine.dispose()
    return _run_alembic_command(url, "downgrade", revision)


def cleanup_owned_schema(
    connection: sa.Connection,
    *,
    expected_database: str,
    run_marker: str,
) -> None:
    verify_exact_ownership(
        connection,
        expected_database=expected_database,
        run_marker=run_marker,
    )
    connection.exec_driver_sql("DROP SCHEMA public CASCADE")
    connection.exec_driver_sql("CREATE SCHEMA public")


@contextmanager
def owned_empty_test_schema(
    engine: sa.Engine,
    *,
    expected_database: str,
) -> Iterator[str]:
    run_marker = secrets.token_hex(32)
    cleanup_armed = False
    try:
        with engine.begin() as connection:
            actual_database = connection.scalar(
                sa.text("SELECT current_database()")
            )
            if actual_database != expected_database:
                fail_closed(
                    "refusing setup outside the exact configured test database"
                )
            existing_objects = public_schema_user_objects(connection)
            if existing_objects:
                fail_closed(
                    "public schema is not empty: " + ", ".join(existing_objects)
                )
            connection.exec_driver_sql(
                f"CREATE TABLE public.{OWNERSHIP_MARKER_TABLE} "
                "(run_marker text PRIMARY KEY)"
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO public.{OWNERSHIP_MARKER_TABLE} "
                    "(run_marker) VALUES (:marker)"
                ),
                {"marker": run_marker},
            )
        cleanup_armed = True
        yield run_marker
    finally:
        if cleanup_armed:
            with engine.begin() as connection:
                cleanup_owned_schema(
                    connection,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )


@contextmanager
def migrated_test_database(
    revision: str,
) -> Iterator[tuple[URL, sa.Engine]]:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", revision)
            yield url, engine
    finally:
        engine.dispose()
