from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings

ADMIN_SESSION_TOKEN_TYPE = "admin_session"
ADMIN_SESSION_SCOPE = "admin"
_LEGACY_ADMIN_CLAIMS = frozenset(
    {"sub", "exp", "iat", "nbf", "jti", "iss", "aud"}
)

bearer = HTTPBearer(auto_error=False)


def _canonical_admin_subject(claims: dict[str, object]) -> str:
    subject = claims.get("sub")
    if (
        type(subject) is not str
        or not 1 <= len(subject) <= 255
        or not subject.isascii()
        or not subject.isdigit()
        or int(subject) <= 0
        or subject != str(int(subject))
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator subject",
        )
    return subject


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    if "exp" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session expiration required",
        )

    _canonical_admin_subject(payload)

    explicit_admin_session = (
        payload.get("token_type") == ADMIN_SESSION_TOKEN_TYPE
        and payload.get("scope") == ADMIN_SESSION_SCOPE
    )
    legacy_admin_session = (
        "token_type" not in payload
        and "scope" not in payload
        and set(payload).issubset(_LEGACY_ADMIN_CLAIMS)
    )
    if not explicit_admin_session and not legacy_admin_session:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin session required",
        )

    return payload


async def require_admin_subject(
    claims: dict[str, object] = Depends(require_admin),  # noqa: B008
) -> str:
    return _canonical_admin_subject(claims)


AdminSubject = Annotated[str, Depends(require_admin_subject)]
