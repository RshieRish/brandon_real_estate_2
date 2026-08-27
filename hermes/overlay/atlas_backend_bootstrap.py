#!/usr/bin/env python3
"""Persist the Atlas MCP configuration only when its two bridge vars exist."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

OVERLAY_DIRECTORY = Path(__file__).resolve().parent
DEPLOYED_MANIFEST_PATH = OVERLAY_DIRECTORY / "atlas_backend_overlay_manifest.json"
MANIFEST_PATH = (
    DEPLOYED_MANIFEST_PATH
    if DEPLOYED_MANIFEST_PATH.exists()
    else OVERLAY_DIRECTORY / "manifest.json"
)
_CONFIG_BACKUP_NAME = ".sydney-durable-context-config-backup.yaml"
_CONFIG_BACKUP_VERSION = 1


def load_manifest() -> dict[str, Any]:
    loaded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Atlas overlay manifest must contain an object.")
    return loaded


def _tool_include(manifest: dict[str, Any] | None = None) -> list[str]:
    manifest = manifest if manifest is not None else load_manifest()
    return list(manifest["tools"]["include"])


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


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


def install_managed_skills(
    hermes_home: Path,
    manifest: dict[str, Any],
    *,
    asset_root: Path = Path("/app"),
) -> list[dict[str, object]]:
    """Verify and atomically install only the skills pinned by the image manifest."""
    managed = manifest.get("managed_skills") or {}
    if not isinstance(managed, dict):
        raise ValueError("managed skill manifest must contain an object")
    home_root = hermes_home.resolve()
    asset_root = asset_root.resolve()
    proofs: list[dict[str, object]] = []
    for name, raw in sorted(managed.items()):
        if not isinstance(raw, dict):
            raise ValueError("managed skill manifest entry is invalid")
        expected = str(raw.get("sha256") or "")
        source = (asset_root / str(raw.get("deployed_source") or "")).resolve()
        try:
            source.relative_to(asset_root)
        except ValueError as exc:
            raise ValueError(
                f"managed skill source escapes asset root: {name}"
            ) from exc
        destination = (home_root / str(raw.get("destination") or "")).resolve()
        try:
            destination.relative_to(home_root)
        except ValueError as exc:
            raise ValueError(
                f"managed skill destination escapes Hermes home: {name}"
            ) from exc
        contents = source.read_bytes()
        actual = hashlib.sha256(contents).hexdigest()
        if actual != expected:
            raise ValueError(f"managed skill hash mismatch: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        changed = _atomic_write(destination, contents)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError(f"managed skill install verification failed: {name}")
        proofs.append({"name": name, "sha256": expected, "changed": changed})
    return proofs


def _setting_snapshot(config: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "present": key in config,
        "value": copy.deepcopy(config.get(key)),
    }


def _nested_setting_snapshot(
    config: dict[str, Any], container_name: str, key: str
) -> dict[str, Any]:
    container = config.get(container_name)
    return {
        "container_present": container_name in config,
        "present": isinstance(container, dict) and key in container,
        "value": (
            copy.deepcopy(container.get(key)) if isinstance(container, dict) else None
        ),
    }


def _sydney_config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": _CONFIG_BACKUP_VERSION,
        "session_reset": _setting_snapshot(config, "session_reset"),
        "agent_max_turns": _nested_setting_snapshot(config, "agent", "max_turns"),
        "compression": _setting_snapshot(config, "compression"),
        "tool_guardrails": _setting_snapshot(config, "tool_guardrails"),
        "memory_provider": _nested_setting_snapshot(config, "memory", "provider"),
    }


def _restore_setting(
    config: dict[str, Any], key: str, snapshot: dict[str, Any]
) -> None:
    if snapshot.get("present") is True:
        config[key] = copy.deepcopy(snapshot.get("value"))
    else:
        config.pop(key, None)


def _restore_nested_setting(
    config: dict[str, Any],
    container_name: str,
    key: str,
    snapshot: dict[str, Any],
) -> None:
    container = config.get(container_name)
    if not isinstance(container, dict):
        container = {}
        config[container_name] = container
    if snapshot.get("present") is True:
        container[key] = copy.deepcopy(snapshot.get("value"))
    else:
        container.pop(key, None)
    if snapshot.get("container_present") is not True and not container:
        config.pop(container_name, None)


def _load_config_backup(path: Path) -> dict[str, Any]:
    import yaml

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {
        "session_reset",
        "agent_max_turns",
        "compression",
        "tool_guardrails",
        "memory_provider",
    }
    if (
        not isinstance(loaded, dict)
        or loaded.get("version") != _CONFIG_BACKUP_VERSION
        or not required.issubset(loaded)
        or not all(isinstance(loaded[name], dict) for name in required)
    ):
        raise ValueError("Sydney config backup is invalid.")
    return loaded


def _restore_sydney_config(config: dict[str, Any], snapshot: dict[str, Any]) -> None:
    _restore_setting(config, "session_reset", snapshot["session_reset"])
    _restore_nested_setting(
        config,
        "agent",
        "max_turns",
        snapshot["agent_max_turns"],
    )
    _restore_setting(config, "compression", snapshot["compression"])
    _restore_setting(config, "tool_guardrails", snapshot["tool_guardrails"])
    _restore_nested_setting(
        config,
        "memory",
        "provider",
        snapshot["memory_provider"],
    )


def configure_atlas_backend(
    config_path: Path,
    *,
    backend_url: str,
    token: str,
    durable_context_enabled: bool = False,
    external_user_id: str = "",
    external_chat_id: str = "",
    allowed_external_user_ids: set[str] | None = None,
    manifest: dict[str, Any] | None = None,
) -> bool:
    """Preserve unrelated config while adding the local-only, pinned bridge entry."""
    import yaml

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = load_yaml(config_path)
    memory_value = config.get("memory")
    if memory_value is not None and not isinstance(memory_value, dict):
        raise ValueError("Hermes config.yaml memory must contain an object.")
    agent_value = config.get("agent")
    if agent_value is not None and not isinstance(agent_value, dict):
        raise ValueError("Hermes config.yaml agent must contain an object.")
    allowlist = allowed_external_user_ids or set()
    sydney_active = (
        durable_context_enabled
        and bool(external_chat_id)
        and external_user_id in allowlist
    )
    backup_path = config_path.parent / _CONFIG_BACKUP_NAME

    if not backend_url or not token:
        if backup_path.exists():
            _restore_sydney_config(config, _load_config_backup(backup_path))
            _atomic_write(
                config_path,
                yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
            )
            backup_path.unlink(missing_ok=True)
            _fsync_directory(backup_path.parent)
            return True
        if isinstance(memory_value, dict) and memory_value.get("provider") == "sydney":
            memory_value.pop("provider", None)
            return _atomic_write(
                config_path,
                yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
            )
        return False

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
            "include": _tool_include(manifest),
            "resources": False,
            "prompts": False,
        },
    }
    remove_backup_after_write = False
    new_snapshot = (
        _sydney_config_snapshot(config)
        if sydney_active and not backup_path.exists()
        else None
    )
    if sydney_active:
        if backup_path.exists():
            _load_config_backup(backup_path)
        else:
            assert new_snapshot is not None
            _atomic_write(
                backup_path,
                yaml.safe_dump(new_snapshot, sort_keys=False).encode("utf-8"),
            )
        memory = memory_value if isinstance(memory_value, dict) else {}
        if memory_value is None:
            config["memory"] = memory
        config["session_reset"] = {"mode": "none"}
        agent = config.setdefault("agent", {})
        agent["max_turns"] = _bounded_int_env(
            "SYDNEY_CONTEXT_MAX_TURNS", 16, minimum=1, maximum=90
        )
        config["compression"] = {
            "enabled": True,
            "threshold": 0.08,
            "threshold_tokens": _bounded_int_env(
                "SYDNEY_CONTEXT_PROMPT_COMPRESS_TOKENS",
                96_000,
                minimum=64_000,
                maximum=2_000_000,
            ),
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
        memory["provider"] = "sydney"
    elif backup_path.exists():
        _restore_sydney_config(config, _load_config_backup(backup_path))
        remove_backup_after_write = True
    elif isinstance(memory_value, dict) and memory_value.get("provider") == "sydney":
        memory_value.pop("provider", None)
    _atomic_write(
        config_path,
        yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
    )
    if remove_backup_after_write:
        backup_path.unlink(missing_ok=True)
        _fsync_directory(backup_path.parent)
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
    manifest = load_manifest()
    skill_proofs = install_managed_skills(hermes_home, manifest)
    print(json.dumps({"managed_skills": skill_proofs}, sort_keys=True))
    enabled = _enabled(os.getenv("SYDNEY_DURABLE_CONTEXT_ENABLED", ""))
    external_user_id = os.getenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", "").strip()
    external_chat_id = os.getenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", "").strip()
    allowed = _allowlist(os.getenv("SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", ""))
    configure_atlas_backend(
        hermes_home / "config.yaml",
        backend_url=os.getenv("BRANDON_BACKEND_URL", ""),
        token=os.getenv("BRANDON_AGENT_CONTROL_TOKEN", ""),
        durable_context_enabled=enabled,
        external_user_id=external_user_id,
        external_chat_id=external_chat_id,
        allowed_external_user_ids=allowed,
        manifest=manifest,
    )
    if enabled and external_chat_id and external_user_id in allowed:
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
