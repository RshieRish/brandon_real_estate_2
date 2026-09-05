from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
TASK1_TESTS = (
    "tests/test_gmail_task_postgres_contract.py",
    "tests/test_integration_runtime_migration.py",
    "tests/test_integration_health_service.py",
    "tests/test_notification_claims.py",
    "tests/test_integration_worker.py",
    "tests/test_integration_worker_deployment.py",
)
TASK2_TESTS = TASK1_TESTS + ("tests/test_gmail_task_intake_migration.py",)
TASK3_TESTS = TASK2_TESTS + (
    "tests/test_gmail_history_adapter.py",
    "tests/test_gmail_history_service.py",
    "tests/test_gmail_history_cursor_recovery.py",
    "tests/test_gmail_message_processing.py",
    "tests/test_gmail_agent_control_origins.py",
    "tests/test_workspace_oauth.py",
    "tests/test_atlas_backend_mcp.py",
    "tests/test_agent_control_workspace_actions.py",
    "tests/test_agent_control_router.py",
    "tests/test_workspace_actions.py",
)
TASK4_TESTS = TASK3_TESTS + (
    "tests/test_gmail_task_extractor.py",
    "tests/test_crm_task_suggestions.py",
)
TASK5_TESTS = TASK4_TESTS + (
    "tests/test_sydney_task_review_migration.py",
    "tests/test_sydney_clarifications.py",
    "tests/test_sydney_telegram_dispatcher.py",
)
TASK6_TESTS = TASK5_TESTS + (
    "tests/test_task_suggestion_approval.py",
    "tests/test_gmail_task_intake_admin.py",
    "tests/test_agent_control_crm.py",
    "tests/test_agent_control_transactional_audit.py",
    "tests/test_gmail_task_router_registration.py",
)
TASK9_TESTS = TASK6_TESTS + ("tests/test_gmail_task_intake_e2e.py",)
TASK13_CONTEXT_TESTS = (
    "tests/test_sydney_context_contracts.py",
    "tests/test_sydney_context_redaction.py",
    "tests/test_sydney_context_models.py",
    "tests/test_sydney_context_migration.py",
    "tests/test_sydney_context_service.py",
    "tests/test_sydney_context_retrieval.py",
    "tests/test_sydney_context_runs.py",
    "tests/test_sydney_context_postgres.py",
    "tests/test_sydney_context_router.py",
    "tests/test_sydney_context_projection.py",
    "tests/test_agent_control_command.py",
    "tests/test_command_contact_notes.py",
    "tests/test_command_contact_sections.py",
    "tests/test_command_contacts_service.py",
    "tests/test_command_contacts_router.py",
    "tests/test_sydney_context_e2e.py",
)
SYDNEY_COMMAND_CARD_TESTS = (
    "tests/test_card_campaign_migration.py",
    "tests/test_card_campaign_models.py",
    "tests/test_card_campaign_service.py",
    "tests/test_command_cards_router.py",
    "tests/test_agent_control_cards.py",
)
COMMAND_CAPTURE_REPAIR_TESTS = (
    "tests/test_command_archive_browser.py",
    "tests/test_command_contact_capture_content.py",
    "tests/test_command_contact_capture_timeline.py",
    "tests/test_command_contact_timeline.py",
    "tests/test_command_contact_timeline_html.py",
    "tests/test_command_contact_timeline_snapshot.py",
    "tests/test_command_contact_timeline_alignment.py",
    "tests/test_command_contact_address_repair.py",
    "tests/test_command_contact_address_repair_cli.py",
    "tests/test_command_contact_address_repair_postgres.py",
    "tests/test_command_contact_section_presentation.py",
    "tests/test_card_campaign_address_refresh.py",
)
TASK4_EXPLICIT_TRIGGER_PATHS = (
    "backend/tests/test_atlas_backend_mcp.py",
    "backend/tests/test_agent_control_router.py",
    "backend/tests/test_agent_control_workspace_actions.py",
    "backend/tests/test_gmail_agent_control_origins.py",
    "backend/tests/test_gmail_history_adapter.py",
    "backend/tests/test_gmail_history_cursor_recovery.py",
    "backend/tests/test_gmail_history_service.py",
    "backend/tests/test_gmail_message_processing.py",
    "backend/tests/test_gmail_task_extractor.py",
    "backend/tests/test_integration_worker.py",
    "backend/tests/test_integration_worker_deployment.py",
    "backend/tests/test_crm_task_suggestions.py",
    "backend/tests/test_workspace_actions.py",
    "backend/tests/test_workspace_oauth.py",
)


def test_ci_preserves_only_failed_synthetic_contact_screenshots_without_weakening_gate() -> None:
    workflow = (
        REPOSITORY_ROOT / ".github/workflows/gmail-sydney-task-intake.yml"
    ).read_text(encoding="utf-8")
    marker = "- name: Preserve failed synthetic contact screenshots"
    assert marker in workflow
    artifact = workflow.split(marker, 1)[1].split("- name:", 1)[0]
    assert "if: failure()" in artifact
    assert "uses: actions/upload-artifact@v4" in artifact
    assert "retention-days: 3" in artifact
    assert "frontend/test-results/command-contacts-visual-*/contact-*-actual.png" in artifact
    assert "frontend/test-results/command-contacts-visual-*/contact-*-diff.png" in artifact
    assert "trace.zip" not in artifact and "storageState" not in artifact
    gate = workflow.split("- name: Run Sydney Command contact browser gates", 1)[1].split("- name:", 1)[0]
    assert "--update-snapshots" not in gate and "continue-on-error" not in gate
    assert "e2e/command-archive.spec.ts" in gate


def test_worker_dockerfile_and_railway_config_use_only_the_worker_contract() -> None:
    dockerfile_path = BACKEND_ROOT / "Dockerfile.worker"
    railway_path = BACKEND_ROOT / "railway.integration-worker.json"
    assert dockerfile_path.is_file()
    assert railway_path.is_file()

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    normalized = dockerfile.lower()
    assert "python:3.12-slim" in normalized
    assert "COPY requirements.txt ." in dockerfile
    assert "COPY . ." in dockerfile
    assert "COPY backend/" not in dockerfile
    assert 'CMD ["python", "-m", "workers.integration_worker"]' in dockerfile
    assert "workers.integration_worker" in dockerfile
    for forbidden in ("healthcheck", "curl", "wget", "uvicorn main:app"):
        assert forbidden not in normalized

    railway = json.loads(railway_path.read_text(encoding="utf-8"))
    assert railway["build"] == {
        "builder": "DOCKERFILE",
        "dockerfilePath": "Dockerfile.worker",
    }
    assert railway["deploy"]["startCommand"] == ("python -m workers.integration_worker")
    assert railway["deploy"]["healthcheckPath"] == "/health"
    assert railway["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert "/ready" not in json.dumps(railway).lower()
    assert "uvicorn main:app --workers 2" not in json.dumps(railway).lower()


def test_worker_build_inputs_resolve_from_documented_backend_context() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Set root directory to `backend/`" in readme
    railway = json.loads(
        (BACKEND_ROOT / "railway.integration-worker.json").read_text(encoding="utf-8")
    )
    context_root = BACKEND_ROOT
    dockerfile_path = context_root / railway["build"]["dockerfilePath"]
    assert dockerfile_path == BACKEND_ROOT / "Dockerfile.worker"
    assert dockerfile_path.is_file()

    for line in dockerfile_path.read_text(encoding="utf-8").splitlines():
        if not line.strip().upper().startswith("COPY "):
            continue
        fields = shlex.split(line)
        assert fields[0].upper() == "COPY"
        assert len(fields) >= 3
        for source in fields[1:-1]:
            source_path = Path(source)
            assert not source_path.is_absolute()
            assert ".." not in source_path.parts
            assert (context_root / source_path).exists(), (
                f"Docker COPY source does not exist in backend context: {source}"
            )


def test_worker_source_uses_first_completed_and_web_source_has_no_worker_schedule() -> (
    None
):
    worker_source = (BACKEND_ROOT / "workers" / "integration_worker.py").read_text(
        encoding="utf-8"
    )
    assert "asyncio.FIRST_COMPLETED" in worker_source
    assert "asyncio.wait(" in worker_source
    assert "server.should_exit = True" in worker_source
    assert "return_exceptions=True" in worker_source
    assert "TaskGroup" not in worker_source

    main_source = (BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
    assert "workers.integration_worker" not in main_source
    assert "run_integration_scheduler" not in main_source
    assert "GMAIL_TASK_INTAKE_ENABLED" not in main_source
    assert "SYDNEY_TASK_QUESTIONS_ENABLED" not in main_source


def test_ready_promotion_probe_uses_only_python_standard_library() -> None:
    probe_path = BACKEND_ROOT / "scripts" / "check_integration_worker.py"
    assert probe_path.is_file()
    source = probe_path.read_text(encoding="utf-8")
    assert "urllib.request" in source
    assert "json" in source
    for forbidden in ("requests", "httpx", "curl", "wget", "subprocess"):
        assert forbidden not in source

    expected_body = {
        "status": "ready",
        "service": "integration-worker",
        "database": "ok",
        "migration": "ok",
        "heartbeat": "ok",
        "job_registry": "ok",
    }

    seen_paths: list[str] = []

    class ReadyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen_paths.append(self.path)
            body = json.dumps(expected_body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(probe_path),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout",
                "2",
            ],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "integration-worker ready"
    assert seen_paths == ["/ready"]


def test_ready_promotion_probe_fails_closed_on_bad_status_body_and_timeout() -> None:
    probe_path = BACKEND_ROOT / "scripts" / "check_integration_worker.py"

    cases = (
        (200, b'{"status":"ready","service":"integration-worker","extra":"secret"}', 0),
        (503, b"provider secret account@example.test", 0),
        (200, b"not-json private-token", 0),
        (200, b"{}", 0.3),
    )
    for status_code, response_body, delay in cases:
        seen_paths: list[str] = []

        class FailureHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                seen_paths.append(self.path)
                if delay:
                    __import__("time").sleep(delay)
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *_args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), FailureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(probe_path),
                    "--base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--timeout",
                    "0.1",
                ],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        assert completed.returncode != 0
        assert seen_paths == ["/ready"]
        assert completed.stdout == ""
        assert completed.stderr.strip() == "integration-worker not ready"
        for forbidden in (
            "secret",
            "example.test",
            "private-token",
            str(server.server_port),
        ):
            assert forbidden not in completed.stderr


def test_gmail_sydney_postgres_matrix_has_bounded_slow_runner_headroom() -> None:
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "gmail-sydney-task-intake.yml"
    ).read_text(encoding="utf-8")
    runtime_header = re.search(
        r"(?m)^  task1-runtime:\n    runs-on: ubuntu-latest\n"
        r"    timeout-minutes: (?P<minutes>\d+)\n",
        workflow,
    )
    assert runtime_header is not None
    assert int(runtime_header.group("minutes")) == 30


def test_gmail_sydney_workflow_is_scoped_tls_postgresql16_through_task9() -> None:
    workflow_path = (
        REPOSITORY_ROOT / ".github" / "workflows" / "gmail-sydney-task-intake.yml"
    )
    assert workflow_path.is_file()
    workflow = workflow_path.read_text(encoding="utf-8")
    for required in (
        "postgres:16-alpine",
        "POSTGRES_CONTAINER: gmail-sydney-postgres",
        "GMAIL_TASK_TEST_DATABASE_NAME: brandon_gmail_sydney_ci_test",
        "GMAIL_TASK_TEST_DATABASE_URL:",
        "DATABASE_URL:",
        "GMAIL_HISTORY_DATABASE_URL:",
        "GMAIL_PARTICIPANT_HASH_KEY: gmail-sydney-ci-participant-hash-key-only",
        "GEMINI_API_KEY: gmail-sydney-ci-no-provider-calls",
        'INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS: "10"',
        'CI: "true"',
        "SSL_CERT_FILE:",
        "ALTER SYSTEM SET ssl = 'on'",
        "PostgreSQL did not remain ready for TLS setup",
        "hostnossl all all 0.0.0.0/0 reject",
        "pg_stat_ssl",
        'sslmode="verify-full"',
        "backend/alembic/**",
        "backend/models/**",
        "backend/services/**",
        "backend/workers/**",
        "backend/Dockerfile.worker",
        "backend/railway.integration-worker.json",
        "backend/scripts/check_integration_worker.py",
        "hermes/**",
        "docs/deployment/hermes-railway.md",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/src/app/admin/command/task-suggestions/page.tsx",
        "frontend/src/lib/command/task-suggestions.ts",
        "frontend/src/lib/command/task-suggestions.test.ts",
        "frontend/src/components/command/TaskSuggestionsWorkspace.tsx",
        "frontend/src/components/command/TaskSuggestionsWorkspace.test.tsx",
        "frontend/src/components/command/shell/commandNavigation.ts",
        "frontend/src/components/command/shell/commandNavigation.test.ts",
        "frontend/src/components/command/shell/CommandShell.test.tsx",
        "backend/.env.example",
        "backend/config.py",
        "backend/database.py",
        "backend/main.py",
        "backend/requirements.txt",
        "backend/routers/admin_integrations.py",
        "backend/routers/command_task_suggestions.py",
        "backend/routers/agent_control_crm.py",
        "backend/schemas/gmail_task_intake.py",
        "backend/schemas/agent_control_crm.py",
        "backend/tests/test_atlas_backend_mcp.py",
        "backend/tests/test_hermes_overlay.py",
        "backend/tests/test_verify_atlas_tools.py",
        "backend/tests/gmail_task_postgres.py",
        ".github/workflows/gmail-sydney-task-intake.yml",
        "if: always()",
        "docker rm --force gmail-sydney-postgres",
        'rm -f -- "$SSL_CERT_FILE" "${SSL_CERT_FILE%.crt}.key"',
        'rmdir -- "$(dirname "$SSL_CERT_FILE")"',
        "hostnossl all all ::/0 reject",
        "server.key",
        'docker restart "$POSTGRES_CONTAINER"',
    ):
        assert required in workflow
    pytest_step = re.search(
        r"name: Run the Task 1 through Task 9 persistence, concurrency, and E2E contracts"
        r"(?P<body>.*?)"
        r"\n\s+- name:",
        workflow,
        flags=re.DOTALL,
    )
    assert pytest_step is not None
    assert (
        tuple(re.findall(r"tests/[a-z0-9_]+\.py", pytest_step.group("body")))
        == TASK9_TESTS + TASK13_CONTEXT_TESTS + SYDNEY_COMMAND_CARD_TESTS + COMMAND_CAPTURE_REPAIR_TESTS
    )
    assert workflow.count('"backend/tests/test_gmail_task_intake_e2e.py"') == 2

    task12_step = re.search(
        r"name: Run the exact MCP, overlay, spool, and retry contracts\n"
        r"\s+working-directory: backend\n"
        r"(?P<body>.*?)"
        r"\n\s+- name: Verify the exact 27-tool JSON-RPC registry",
        workflow,
        flags=re.DOTALL,
    )
    assert task12_step is not None
    assert tuple(re.findall(r"tests/[a-z0-9_]+\.py", task12_step.group("body"))) == (
        "tests/test_atlas_backend_mcp.py",
        "tests/test_hermes_overlay.py",
        "tests/test_verify_atlas_tools.py",
        "tests/test_sydney_spool.py",
        "tests/test_sydney_memory_provider.py",
        "tests/test_sydney_retry.py",
        "tests/test_sydney_backfill.py",
        "tests/test_sydney_context_e2e.py",
        "tests/test_sydney_celebration_replies.py",
    )
    assert 'export CRM_TASK_TEST_DATABASE_NAME="$GMAIL_TASK_TEST_DATABASE_NAME"' in pytest_step.group("body")
    assert 'export CRM_TASK_TEST_DATABASE_URL="$GMAIL_TASK_TEST_DATABASE_URL"' in pytest_step.group("body")
    assert "7224d7c1a4dcffe9304f49bc843f55716f5561b4" in workflow
    assert "77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5" in workflow
    task12_job = re.search(
        r"^  task12-hermes-overlay:\n(?P<body>.*?)(?=^  [a-z0-9_-]+:|\Z)",
        workflow,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert task12_job is not None
    assert '"pytest-asyncio==1.3.0"' in task12_job.group("body")
    assert '"jsonschema==4.26.0"' in task12_job.group("body")

    assert 'if [[ "$GMAIL_TASK_TEST_DATABASE_NAME" != *_test ]]' in workflow
    assert 'if [[ "$url_database" != "$GMAIL_TASK_TEST_DATABASE_NAME" ]]' in workflow
    assert workflow.count('"backend/tests/gmail_task_postgres.py"') == 2
    for path in TASK4_EXPLICIT_TRIGGER_PATHS:
        assert workflow.count(f'"{path}"') == 2

    env_urls = {
        name: re.search(rf"^\s+{name}: (?P<url>\S+)$", workflow, re.MULTILINE)
        for name in (
            "DATABASE_URL",
            "GMAIL_HISTORY_DATABASE_URL",
            "GMAIL_TASK_TEST_DATABASE_URL",
        )
    }
    assert all(match is not None for match in env_urls.values())
    rendered_urls = {match.group("url") for match in env_urls.values() if match}
    assert len(rendered_urls) == 1
    assert next(iter(rendered_urls)).endswith(
        "/brandon_gmail_sydney_ci_test?ssl=require"
    )


def test_existing_crm_workflow_still_runs_the_revision81_ancestor_contract() -> None:
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "crm-task-lifecycle-migration.yml"
    ).read_text(encoding="utf-8")
    assert '"backend/alembic/**"' in workflow
    assert "tests/test_crm_task_lifecycle_migration.py" in workflow
    assert "postgres:16-alpine" in workflow
    assert "docker rm --force crm-task-lifecycle-postgres" in workflow
