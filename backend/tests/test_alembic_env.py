from __future__ import annotations

import asyncio
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import alembic


def _load_alembic_env(monkeypatch, events: list[object]):
    fake_config = SimpleNamespace(
        config_file_name=None,
        config_ini_section="alembic",
        get_section=lambda *_args, **_kwargs: {},
    )
    transaction_open = False

    @contextmanager
    def begin_transaction():
        nonlocal transaction_open
        transaction_open = True
        try:
            yield
        finally:
            transaction_open = False

    fake_context = SimpleNamespace(
        config=fake_config,
        configure=lambda **_kwargs: events.append("configure"),
        begin_transaction=begin_transaction,
        run_migrations=lambda: events.append("run_migrations"),
        is_offline_mode=lambda: False,
    )
    monkeypatch.setattr(alembic, "context", fake_context)
    monkeypatch.setattr(asyncio, "run", lambda coroutine: coroutine.close())

    config_module = ModuleType("config")
    config_module.settings = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test"
    )
    database_module = ModuleType("database")
    database_module.Base = SimpleNamespace(metadata=object())
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "database", database_module)

    models_module = ModuleType("models")
    models_module.__path__ = []
    monkeypatch.setitem(sys.modules, "models", models_module)
    for name in (
        "admin_user",
        "analytics_event",
        "booking",
        "command",
        "command_contacts",
        "command_provenance",
        "content_block",
        "crm_task_lifecycle",
        "funnel",
        "gmail_task_intake",
        "integration_health",
        "lead",
        "notification_job",
        "setting",
        "sydney_tasks",
    ):
        model_module = ModuleType(f"models.{name}")
        monkeypatch.setitem(sys.modules, f"models.{name}", model_module)
        setattr(models_module, name, model_module)

    monkeypatch.setattr(sys, "path", sys.path.copy())
    namespace = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic" / "env.py"),
        run_name="test_alembic_env",
    )
    return namespace["do_run_migrations"], lambda: transaction_open


def test_online_migrations_set_public_search_path_before_running(
    monkeypatch,
) -> None:
    events: list[object] = []
    do_run_migrations, is_transaction_open = _load_alembic_env(
        monkeypatch,
        events,
    )

    class Connection:
        def exec_driver_sql(self, statement: str) -> None:
            assert is_transaction_open()
            events.append(("sql", statement))

    do_run_migrations(Connection())

    search_path_event = ("sql", "SET LOCAL search_path TO public")
    assert search_path_event in events
    assert events.index(search_path_event) < events.index("run_migrations")
