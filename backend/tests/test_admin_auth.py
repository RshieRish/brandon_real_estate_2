"""Admin-session JWT identity and backwards-compatibility contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
import pytest

from config import settings
from middleware.auth import require_admin
from models.admin_user import AdminUser
from routers.auth import login, pwd_context
from schemas.auth import LoginRequest


def credentials_for(payload: dict) -> HTTPAuthorizationCredentials:
    token = jwt.encode(
        {**payload, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class OneUserResult:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class OneUserDB:
    def __init__(self, user):
        self.user = user

    async def execute(self, _statement):
        return OneUserResult(self.user)


async def test_admin_login_mints_explicit_admin_session_claims():
    user = AdminUser(
        id=17,
        email="admin@example.com",
        hashed_password=pwd_context.hash("correct horse battery staple"),
    )

    response = await login(
        LoginRequest(
            email="admin@example.com",
            password="correct horse battery staple",
        ),
        db=OneUserDB(user),
    )
    payload = jwt.decode(
        response.access_token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert payload["sub"] == "17"
    assert payload["token_type"] == "admin_session"
    assert payload["scope"] == "admin"
    assert require_admin(credentials_for(payload))["sub"] == "17"


def test_require_admin_accepts_unexpired_legacy_admin_session():
    payload = require_admin(credentials_for({"sub": "17"}))

    assert payload["sub"] == "17"


def test_require_admin_rejects_admin_session_without_expiration():
    token = jwt.encode(
        {
            "sub": "17",
            "token_type": "admin_session",
            "scope": "admin",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(HTTPException) as error:
        require_admin(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"item_id": 2, "scope": "link_pack_gate"},
        {"sub": "17", "purpose": "calendar_oauth"},
        {"sub": "17", "token_type": "admin_session", "scope": "read_only"},
        {"sub": "17", "token_type": "public_gate", "scope": "admin"},
        {"sub": "17", "token_type": "admin_session"},
        {"sub": "17", "scope": "admin"},
    ],
)
def test_require_admin_rejects_non_admin_token_classes(payload):
    with pytest.raises(HTTPException) as error:
        require_admin(credentials_for(payload))

    assert error.value.status_code in {401, 403}


@pytest.mark.parametrize(
    "subject",
    [None, "", "admin@example.com", "0", "-1", "01", "١٧", 17, True],
)
def test_require_admin_rejects_missing_or_noncanonical_subject(subject):
    payload = {
        "sub": subject,
        "token_type": "admin_session",
        "scope": "admin",
    }
    with pytest.raises(HTTPException) as error:
        require_admin(credentials_for(payload))

    assert error.value.status_code in {401, 403}
