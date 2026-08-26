from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "hermes" / "verify_atlas_tools.py"
MCP_SERVER = REPO_ROOT / "hermes" / "atlas_backend_mcp.py"


def test_verifier_probes_real_server_and_reports_exact_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--server", str(MCP_SERVER)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    proof = json.loads(completed.stdout)
    assert proof == {
        "count": 25,
        "exact_expected_order": True,
        "forbidden_present": [],
        "gmail_send_request_id_required": True,
        "gmail_send_request_id_schema": {
            "description": (
                "Caller-supplied idempotency UUID; the bridge never creates or "
                "replaces it."
            ),
            "format": "uuid",
            "type": "string",
        },
        "jsonrpc_method": "tools/list",
        "names": [
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
            "context_history_search",
            "command_contacts_search",
            "command_contact_audience_preview",
        ],
        "original_22_unchanged": True,
        "unique_count": 25,
    }


def test_verifier_fails_closed_for_a_nonmatching_registry(tmp_path: Path) -> None:
    fake_server = tmp_path / "fake_mcp.py"
    fake_server.write_text(
        """\
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"},
        }
    elif request.get("method") == "tools/list":
        result = {"tools": []}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--server", str(fake_server)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.strip() == "Atlas tools/list contract mismatch"
