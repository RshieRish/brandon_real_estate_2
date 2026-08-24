#!/usr/bin/env python3
"""Verify the deployed Atlas MCP tools/list contract over stdio JSON-RPC."""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_TOOLS = [
    "status_read",
    "actions_list",
    "leads_recent",
    "bookings_recent",
    "workspace_status",
    "drive_search",
    "drive_file_read",
    "gmail_search",
    "gmail_thread_read",
    "gmail_draft_create",
    "gmail_send",
    "docs_create",
    "sheets_append",
    "calendar_events_read",
    "calendar_event_create",
    "contacts_search",
    "crm_tasks_read",
    "crm_task_suggestions_read",
    "crm_task_clarifications_answer",
    "crm_task_drafts_create",
    "crm_task_suggestions_approval_link",
    "crm_task_suggestions_dismiss_proposal",
]
ORIGINAL_TOOLS = EXPECTED_TOOLS[:16]
FORBIDDEN_TOOLS = {
    "crm_task_suggestions_dismiss",
    "crm_task_suggestions_approve",
    "crm_tasks_create_confirmed",
    "crm_tasks_archive",
    "crm_tasks_restore",
}


def _send(server: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if server.stdin is None:
        raise RuntimeError("missing MCP stdin")
    server.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    server.stdin.flush()


def _wait_for(
    server: subprocess.Popen[str], response_id: int, timeout_seconds: float
) -> dict[str, Any]:
    if server.stdout is None:
        raise RuntimeError("missing MCP stdout")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            [server.stdout], [], [], deadline - time.monotonic()
        )
        if not ready:
            break
        line = server.stdout.readline()
        if not line:
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("id") == response_id:
            return payload
    raise TimeoutError("MCP response deadline exceeded")


def _list_tools(server_path: Path) -> list[dict[str, Any]]:
    server = subprocess.Popen(
        [sys.executable, str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        _send(
            server,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "task8-live-probe",
                        "version": "1.0",
                    },
                },
            },
        )
        initialized = _wait_for(server, 1, 20)
        if "error" in initialized:
            raise RuntimeError("MCP initialize failed")
        _send(
            server,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        _send(
            server,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        listed = _wait_for(server, 2, 20)
        if "error" in listed:
            raise RuntimeError("MCP tools/list failed")
        tools = listed.get("result", {}).get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list returned an invalid result")
        return tools
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=2)


def _build_proof(tools: list[dict[str, Any]]) -> dict[str, Any]:
    names = [tool.get("name") for tool in tools]
    by_name = {tool.get("name"): tool for tool in tools}
    gmail_send = by_name.get("gmail_send", {})
    send_schema = gmail_send.get("inputSchema", {})
    request_schema = send_schema.get("properties", {}).get("request_id", {})
    return {
        "jsonrpc_method": "tools/list",
        "count": len(names),
        "unique_count": len(set(names)),
        "names": names,
        "exact_expected_order": names == EXPECTED_TOOLS,
        "original_16_unchanged": names[:16] == ORIGINAL_TOOLS,
        "forbidden_present": sorted(FORBIDDEN_TOOLS.intersection(names)),
        "gmail_send_request_id_required": "request_id"
        in send_schema.get("required", []),
        "gmail_send_request_id_schema": request_schema,
    }


def _contract_matches(proof: dict[str, Any]) -> bool:
    request_schema = proof["gmail_send_request_id_schema"]
    return bool(
        proof["count"] == 22
        and proof["unique_count"] == 22
        and proof["exact_expected_order"]
        and proof["original_16_unchanged"]
        and proof["forbidden_present"] == []
        and proof["gmail_send_request_id_required"]
        and request_schema.get("type") == "string"
        and request_schema.get("format") == "uuid"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server",
        type=Path,
        default=Path("/app/atlas_backend_mcp.py"),
        help="Path to the Atlas MCP stdio server",
    )
    args = parser.parse_args()
    try:
        proof = _build_proof(_list_tools(args.server))
    except Exception:
        print("Atlas tools/list probe failed", file=sys.stderr)
        return 1
    if not _contract_matches(proof):
        print("Atlas tools/list contract mismatch", file=sys.stderr)
        return 2
    print(json.dumps(proof, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
