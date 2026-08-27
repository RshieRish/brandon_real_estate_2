#!/usr/bin/env python3
"""Apply the pinned Atlas MCP overlay to an exact Hermes template checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


OVERLAY_DIRECTORY = Path(__file__).resolve().parent
HERMES_DIRECTORY = OVERLAY_DIRECTORY.parent
MANIFEST_PATH = OVERLAY_DIRECTORY / "manifest.json"
OVERLAY_TARGETS = {
    "Dockerfile",
    "start.sh",
    "atlas_backend_mcp.py",
    "atlas_backend_bootstrap.py",
    "atlas_backend_overlay_manifest.json",
    "atlas_backend_operations_skill.md",
    "install_sydney_overlay.py",
    "sydney_spool.py",
    "sydney_memory_provider.py",
    "sydney_retry.py",
    "sydney_backfill.py",
    "sydney_recovery.py",
    "sydney_runtime.py",
    "sydney_gateway.py",
}


def load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _checkout_commit(source: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _baseline_file(source: Path, name: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), "show", f"HEAD:{name}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _working_tree_status(source: Path) -> set[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
    )
    paths: set[str] = set()
    for entry in completed.stdout.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 4:
            raise ValueError("could not parse Hermes checkout status")
        status = entry[:2]
        if status[0:1] in {b"R", b"C"} or status[1:2] in {b"R", b"C"}:
            raise ValueError(
                "Hermes checkout renames/copies are not supported by the overlay"
            )
        paths.add(entry[3:].decode("utf-8"))
    return paths


def _insert_once(contents: str, marker: str, insertion: str) -> str:
    if insertion in contents:
        return contents
    if marker not in contents:
        raise ValueError(f"expected overlay anchor is missing: {marker}")
    return contents.replace(marker, f"{marker}\n{insertion}", 1)


def _insert_before_once(contents: str, marker: str, insertion: str) -> str:
    if insertion in contents:
        return contents
    if marker not in contents:
        raise ValueError(f"expected overlay anchor is missing: {marker}")
    return contents.replace(marker, f"{insertion}\n{marker}", 1)


def _desired_contents(source: Path) -> dict[Path, bytes]:
    dockerfile = _baseline_file(source, "Dockerfile")
    start_script = _baseline_file(source, "start.sh")
    dockerfile = _insert_once(
        dockerfile,
        "COPY start.sh /app/start.sh",
        "COPY atlas_backend_mcp.py /app/atlas_backend_mcp.py",
    )
    dockerfile = _insert_once(
        dockerfile,
        "COPY start.sh /app/start.sh",
        "COPY atlas_backend_bootstrap.py /app/atlas_backend_bootstrap.py",
    )
    dockerfile = _insert_once(
        dockerfile,
        "COPY start.sh /app/start.sh",
        "COPY atlas_backend_overlay_manifest.json /app/atlas_backend_overlay_manifest.json",
    )
    dockerfile = _insert_once(
        dockerfile,
        "COPY start.sh /app/start.sh",
        "COPY atlas_backend_operations_skill.md /app/atlas_backend_operations_skill.md",
    )
    pre_clone_copies = "\n".join(
        [
            "COPY install_sydney_overlay.py /app/install_sydney_overlay.py",
            "COPY sydney_spool.py /app/sydney_spool.py",
            "COPY sydney_memory_provider.py /app/sydney_memory_provider.py",
            "COPY sydney_retry.py /app/sydney_retry.py",
            "COPY sydney_backfill.py /app/sydney_backfill.py",
            "COPY sydney_recovery.py /app/sydney_recovery.py",
            "COPY sydney_runtime.py /app/sydney_runtime.py",
            "COPY sydney_gateway.py /app/sydney_gateway.py",
            "COPY atlas_backend_overlay_manifest.json /app/sydney_overlay_manifest.json",
        ]
    )
    dockerfile = _insert_before_once(
        dockerfile,
        "RUN git clone --depth 1 --branch ${HERMES_REF} https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \\",
        pre_clone_copies,
    )
    dockerfile = _insert_before_once(
        dockerfile,
        "    uv pip install --system --no-cache -e",
        "    python /app/install_sydney_overlay.py --source /opt/hermes-agent && \\",
    )
    start_script = _insert_before_once(
        start_script,
        "exec python /app/server.py",
        "python /app/atlas_backend_bootstrap.py",
    )
    return {
        source / "Dockerfile": dockerfile.encode("utf-8"),
        source / "start.sh": start_script.encode("utf-8"),
        source / "atlas_backend_mcp.py": (
            HERMES_DIRECTORY / "atlas_backend_mcp.py"
        ).read_bytes(),
        source / "atlas_backend_bootstrap.py": (
            OVERLAY_DIRECTORY / "atlas_backend_bootstrap.py"
        ).read_bytes(),
        source / "atlas_backend_overlay_manifest.json": MANIFEST_PATH.read_bytes(),
        source / "atlas_backend_operations_skill.md": (
            HERMES_DIRECTORY / "skills/atlas-backend-operations/SKILL.md"
        ).read_bytes(),
        source / "install_sydney_overlay.py": (
            OVERLAY_DIRECTORY / "install_sydney_overlay.py"
        ).read_bytes(),
        source / "sydney_spool.py": (
            OVERLAY_DIRECTORY / "sydney_spool.py"
        ).read_bytes(),
        source / "sydney_memory_provider.py": (
            OVERLAY_DIRECTORY / "sydney_memory_provider.py"
        ).read_bytes(),
        source / "sydney_retry.py": (
            OVERLAY_DIRECTORY / "sydney_retry.py"
        ).read_bytes(),
        source / "sydney_backfill.py": (
            OVERLAY_DIRECTORY / "sydney_backfill.py"
        ).read_bytes(),
        source / "sydney_recovery.py": (
            OVERLAY_DIRECTORY / "sydney_recovery.py"
        ).read_bytes(),
        source / "sydney_runtime.py": (
            OVERLAY_DIRECTORY / "sydney_runtime.py"
        ).read_bytes(),
        source / "sydney_gateway.py": (
            OVERLAY_DIRECTORY / "sydney_gateway.py"
        ).read_bytes(),
    }


def _is_pristine(source: Path, desired: dict[Path, bytes]) -> bool:
    return (
        (source / "Dockerfile").read_bytes()
        == _baseline_file(source, "Dockerfile").encode("utf-8")
        and (source / "start.sh").read_bytes()
        == _baseline_file(source, "start.sh").encode("utf-8")
        and all(
            not target.exists()
            for target in desired
            if target.name not in {"Dockerfile", "start.sh"}
        )
    )


def _validate_source_state(source: Path, desired: dict[Path, bytes]) -> bool:
    dirty_paths = _working_tree_status(source)
    exact_overlay = all(
        target.is_file() and target.read_bytes() == contents
        for target, contents in desired.items()
    )
    if exact_overlay:
        if dirty_paths == OVERLAY_TARGETS:
            return True
        raise ValueError("Hermes checkout has unrelated or tampered overlay changes.")
    if dirty_paths:
        raise ValueError(
            "Hermes checkout must be pristine before applying the overlay."
        )
    if not _is_pristine(source, desired):
        raise ValueError("Hermes checkout has a partial or tampered overlay state.")
    return False


def _stage_contents(target: Path, contents: bytes, mode: int) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".atlas-overlay-", dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            os.fchmod(temporary_file.fileno(), mode)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _replace_all(desired: dict[Path, bytes]) -> None:
    originals = {
        target: (
            target.exists(),
            target.read_bytes() if target.exists() else b"",
            stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644,
        )
        for target in desired
    }
    staged: dict[Path, Path] = {}
    applied: list[Path] = []
    try:
        for target, contents in desired.items():
            staged[target] = _stage_contents(target, contents, originals[target][2])
        for target in desired:
            os.replace(staged[target], target)
            applied.append(target)
    except Exception:
        for target in reversed(applied):
            existed, contents, mode = originals[target]
            if existed:
                rollback = _stage_contents(target, contents, mode)
                os.replace(rollback, target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)


def apply_overlay(source: Path) -> None:
    """Apply only to the pinned pristine checkout, or no-op on exact overlay state."""
    manifest = load_manifest()
    expected_commit = str(manifest["upstream"]["commit"])  # type: ignore[index]
    if _checkout_commit(source) != expected_commit:
        raise ValueError(
            "Hermes source checkout does not match the pinned overlay commit."
        )
    if not (source / "Dockerfile").is_file() or not (source / "start.sh").is_file():
        raise ValueError("Hermes source checkout is missing Dockerfile or start.sh.")
    desired = _desired_contents(source)
    if _validate_source_state(source, desired):
        return
    _replace_all(desired)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to a detached checkout of the pinned Hermes template commit.",
    )
    args = parser.parse_args()
    apply_overlay(args.source.resolve())


if __name__ == "__main__":
    main()
