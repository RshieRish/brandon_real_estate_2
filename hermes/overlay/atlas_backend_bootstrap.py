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


def configure_atlas_backend(config_path: Path, *, backend_url: str, token: str) -> bool:
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
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        config_path,
        yaml.safe_dump(config, sort_keys=False).encode("utf-8"),
    )
    return True


def main() -> None:
    hermes_home = Path(os.getenv("HERMES_HOME", "/data/.hermes"))
    configure_atlas_backend(
        hermes_home / "config.yaml",
        backend_url=os.getenv("BRANDON_BACKEND_URL", ""),
        token=os.getenv("BRANDON_AGENT_CONTROL_TOKEN", ""),
    )


if __name__ == "__main__":
    main()
