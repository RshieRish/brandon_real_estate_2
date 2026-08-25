#!/usr/bin/env python3
"""Persist the Atlas MCP configuration only when its two bridge vars exist."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


OVERLAY_DIRECTORY = Path(__file__).resolve().parent
DEPLOYED_MANIFEST_PATH = OVERLAY_DIRECTORY / "atlas_backend_overlay_manifest.json"
MANIFEST_PATH = (
    DEPLOYED_MANIFEST_PATH
    if DEPLOYED_MANIFEST_PATH.exists()
    else OVERLAY_DIRECTORY / "manifest.json"
)


def _tool_include() -> list[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return list(manifest["tools"]["include"])


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Hermes config.yaml must contain an object.")
    return loaded


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, contents: bytes) -> bool:
    if path.exists() and path.read_bytes() == contents:
        return False
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".atlas-bootstrap-", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            os.fchmod(temporary_file.fileno(), mode)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
        return True
    finally:
        temporary_path.unlink(missing_ok=True)


def configure_atlas_backend(
    config_path: Path,
    *,
    backend_url: str,
    token: str,
    durable_context_enabled: bool = False,
    external_user_id: str = "",
    allowed_external_user_ids: set[str] | None = None,
) -> bool:
    """Preserve unrelated config while adding the local-only, pinned bridge entry."""
    if not backend_url or not token:
        return False

    import yaml

    config = load_yaml(config_path)
    mcp_servers = config.setdefault("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError("Hermes config.yaml mcp_servers must contain an object.")
    mcp_servers["atlas_backend"] = {
        "command": "python",
        "args": ["/app/atlas_backend_mcp.py"],
        "env": {
            "BRANDON_BACKEND_URL": "${BRANDON_BACKEND_URL}",
            "BRANDON_AGENT_CONTROL_TOKEN": "${BRANDON_AGENT_CONTROL_TOKEN}",
        },
        "enabled": True,
        "timeout": 120,
        "connect_timeout": 30,
        "supports_parallel_tool_calls": False,
        "tools": {
            "include": _tool_include(),
            "resources": False,
            "prompts": False,
        },
    }
    config["session_reset"] = {"mode": "none"}
    agent = config.setdefault("agent", {})
    if not isinstance(agent, dict):
        raise ValueError("Hermes config.yaml agent must contain an object.")
    agent["max_turns"] = 16
    config["compression"] = {
        "enabled": True,
        "threshold": 0.08,
        "target": 0.02,
        "protect_last": 20,
        "abort_on_summary_failure": True,
    }
    config["tool_guardrails"] = {
        "enabled": True,
        "exact_failure_limit": 5,
        "same_tool_failure_limit": 8,
        "no_progress_limit": 5,
    }
    memory = config.setdefault("memory", {})
    if not isinstance(memory, dict):
        raise ValueError("Hermes config.yaml memory must contain an object.")
    allowlist = allowed_external_user_ids or set()
    if durable_context_enabled and external_user_id in allowlist:
        memory["provider"] = "sydney"
    elif memory.get("provider") == "sydney":
        memory.pop("provider", None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        config_path,
        yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
    )
    return True


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _allowlist(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def backfill_visible_history(
    *,
    hermes_home: Path,
    external_user_id: str,
    external_chat_id: str,
    display_label: str,
) -> dict[str, Any] | None:
    """Run the bounded, idempotent state.db backfill when history exists."""
    state_db = hermes_home / "state.db"
    if not state_db.is_file() or not external_user_id or not external_chat_id:
        return None
    import sys

    source_root = Path("/opt/hermes-agent")
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from plugins.memory.sydney.sydney_backfill import SydneyBackfill
    from plugins.memory.sydney.sydney_spool import SydneySpool

    spool = SydneySpool(hermes_home / "sydney_spool.db")
    try:
        report = SydneyBackfill(
            state_db=state_db,
            spool=spool,
            platform="telegram",
            external_user_id=external_user_id,
            external_chat_id=external_chat_id,
            display_label=display_label or "Sydney user",
        ).run(page_size=100)
    finally:
        spool.close()
    _atomic_write(
        hermes_home / "sydney_backfill_report.json",
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )
    return report


def main() -> None:
    hermes_home = Path(os.getenv("HERMES_HOME", "/data/.hermes"))
    enabled = _enabled(os.getenv("SYDNEY_DURABLE_CONTEXT_ENABLED", ""))
    external_user_id = os.getenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", "").strip()
    external_chat_id = os.getenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", "").strip()
    allowed = _allowlist(
        os.getenv("SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", "")
    )
    configure_atlas_backend(
        hermes_home / "config.yaml",
        backend_url=os.getenv("BRANDON_BACKEND_URL", ""),
        token=os.getenv("BRANDON_AGENT_CONTROL_TOKEN", ""),
        durable_context_enabled=enabled,
        external_user_id=external_user_id,
        allowed_external_user_ids=allowed,
    )
    if enabled and external_user_id in allowed:
        backfill_visible_history(
            hermes_home=hermes_home,
            external_user_id=external_user_id,
            external_chat_id=external_chat_id,
            display_label=os.getenv(
                "SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL", "Brandon"
            ).strip(),
        )


if __name__ == "__main__":
    main()
