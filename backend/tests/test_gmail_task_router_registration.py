from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


EXPECTED_ROUTES = {
    ("GET", "/api/v1/admin/integrations/gmail-task-intake/status"),
    ("POST", "/api/v1/admin/integrations/gmail-task-intake/check"),
    ("POST", "/api/v1/admin/integrations/gmail-task-intake/backfill"),
    ("POST", "/api/v1/admin/integrations/gmail-task-intake/reprocess/{receipt_id}"),
    ("POST", "/api/v1/admin/integrations/gmail-task-intake/alert-canary"),
    ("GET", "/api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}"),
    (
        "POST",
        "/api/v1/admin/integrations/gmail-task-intake/send-intents/{request_id}/reconcile",
    ),
    (
        "POST",
        "/api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/reconcile",
    ),
    ("POST", "/api/v1/admin/integrations/gmail-task-intake/clarifications/{id}/retry"),
    ("GET", "/api/v1/command/task-suggestions"),
    ("GET", "/api/v1/command/task-suggestions/{suggestion_id}"),
    ("PATCH", "/api/v1/command/task-suggestions/{suggestion_id}"),
    ("POST", "/api/v1/command/task-suggestions/{suggestion_id}/preview"),
    ("POST", "/api/v1/command/task-suggestions/{suggestion_id}/approval/prepare"),
    ("POST", "/api/v1/command/task-suggestions/{suggestion_id}/handoff/exchange"),
    ("POST", "/api/v1/command/task-suggestions/{suggestion_id}/approve"),
    ("POST", "/api/v1/command/task-suggestions/{suggestion_id}/dismiss"),
    ("GET", "/api/v1/agent-control/crm/tasks"),
    ("GET", "/api/v1/agent-control/crm/task-suggestions"),
    ("POST", "/api/v1/agent-control/crm/task-clarifications/answer"),
    ("POST", "/api/v1/agent-control/crm/task-drafts"),
    (
        "POST",
        "/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/approval-link",
    ),
    (
        "POST",
        "/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/dismiss-proposal",
    ),
}


def test_real_app_registers_task6_routes_once_with_unique_operation_ids(
    monkeypatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "task6-non-provider-test-key")
    from main import app

    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    inventory = [
        (method, route.path)
        for route in routes
        for method in route.methods
        if (method, route.path) in EXPECTED_ROUTES
    ]
    assert set(inventory) == EXPECTED_ROUTES
    assert len(inventory) == len(EXPECTED_ROUTES)
    operation_ids = [route.operation_id or route.unique_id for route in routes]
    assert len(operation_ids) == len(set(operation_ids))


def test_task6_routes_reach_auth_or_validation_boundary_not_404_or_405(
    monkeypatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "task6-non-provider-test-key")
    from main import app

    replacements = {
        "{receipt_id}": "00000000-0000-4000-8000-000000000001",
        "{request_id}": "00000000-0000-4000-8000-000000000002",
        "{id}": "00000000-0000-4000-8000-000000000003",
        "{suggestion_id}": "00000000-0000-4000-8000-000000000004",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        for method, template in sorted(EXPECTED_ROUTES):
            path = template
            for placeholder, value in replacements.items():
                path = path.replace(placeholder, value)
            response = client.request(
                method, path, json={} if method != "GET" else None
            )
            assert response.status_code not in {404, 405}, (method, path, response.text)
            assert response.status_code in {401, 403, 422, 503}, (
                method,
                path,
                response.status_code,
                response.text,
            )
