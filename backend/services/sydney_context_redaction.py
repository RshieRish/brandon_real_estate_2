"""Deterministic, irreversible redaction for Sydney's durable history."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedactedContent:
    text: str
    sha256: str
    changed: bool


_STRUCTURAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
        "[REDACTED_BEARER_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:access_token|refresh_token|oauth_token|id_token)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\"'\s&,;}#]+([\"']?)"
        ),
        r"\1[REDACTED_OAUTH_TOKEN]\2",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:api[_-]?key|x-api-key)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\"'\s&,;}#]+([\"']?)"
        ),
        r"\1[REDACTED_API_KEY]\2",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:password|passwd|pwd|client_secret|secret)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\"'\s&,;}]+([\"']?)"
        ),
        r"\1[REDACTED_PASSWORD]\2",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:cookie|set-cookie)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\"'\r\n}]+([\"']?)"
        ),
        r"\1[REDACTED_COOKIE]\2",
    ),
    (
        re.compile(
            r"(?i)([#?&](?:handoff|approval|approval_token|session|nonce)=)"
            r"[^&#\s\"']+"
        ),
        r"\1[REDACTED_SIGNED_FRAGMENT]",
    ),
)


def _redact_structural_secrets(value: str) -> str:
    redacted = value
    for pattern, replacement in _STRUCTURAL_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _redact_known_values(value: str, configured_secrets: Sequence[str]) -> str:
    redacted = value
    unique_secrets = {
        secret
        for secret in configured_secrets
        if isinstance(secret, str) and len(secret) >= 8
    }
    for secret in sorted(unique_secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED_CONFIGURED_SECRET]")
    return redacted


def redact_content(
    value: str,
    *,
    configured_secrets: Sequence[str] = (),
) -> RedactedContent:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    normalized = unicodedata.normalize("NFC", value)
    redacted = _redact_known_values(
        _redact_structural_secrets(normalized),
        configured_secrets,
    )
    digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
    return RedactedContent(
        text=redacted,
        sha256=digest,
        changed=redacted != normalized,
    )


def split_utf8_text(value: str, *, max_chars: int) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be positive")
    return tuple(
        value[start : start + max_chars] for start in range(0, len(value), max_chars)
    ) or ("",)


__all__ = ["RedactedContent", "redact_content", "split_utf8_text"]
