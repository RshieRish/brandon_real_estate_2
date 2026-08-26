"""Deterministic, irreversible redaction for Sydney's durable history."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)


@dataclass(frozen=True, slots=True)
class RedactedContent:
    text: str
    sha256: str
    changed: bool


_URL = re.compile(r"https?://[^\s<>\"']+")
_URL_SECRET_KEYS = frozenset(
    {
        "access_token",
        "approval",
        "approval_token",
        "api_key",
        "apikey",
        "client_secret",
        "code",
        "handoff",
        "id_token",
        "key",
        "nonce",
        "oauth_token",
        "password",
        "refresh_token",
        "session",
        "session_token",
        "sig",
        "signature",
        "state",
        "token",
    }
)
_MAX_NESTED_REDACTION_DEPTH = 4
_MAX_NESTED_JSON_DEPTH = 32
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:authorization|access_token|refresh_token|id_token|oauth_token|"
    r"password|passwd|pwd|api_key|client_secret|cookie|set_cookie|bearer_token|"
    r"token|secret|credential|credentials|handoff)(?:$|_)",
    re.IGNORECASE,
)
_REDACTION_MARKER = re.compile(r"^\[REDACTED_[A-Z0-9_]+\]$")
_ASSIGNMENT_VALUE = (
    r'(?:(?:"(?!\[REDACTED_)[^"\r\n]*")|'
    r"(?:'(?!\[REDACTED_)[^'\r\n]*')|"
    r'(?!\[REDACTED_)[^"\'\s&,;}#]+)'
)


_STRUCTURAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
            r"sk-[A-Za-z0-9_-]{20,})\b"
        ),
        "[REDACTED_PROVIDER_TOKEN]",
    ),
    (
        re.compile(
            r"(?is)(\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b)"
            r"(?=(?:[ \t]*\r?\n){1,3}[ \t]*(?:here|this)\s+is\s+the\s+"
            r"(?:api\s+)?token\b)"
        ),
        "[REDACTED_CONTEXT_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)(\b(?:api\s+|railway\s+|workspace\s+|account\s+)?"
            r"(?:token|credential|api[_ -]?key)\b\s*(?:is|[:=])?\s*)"
            r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9_-]{20,})"
        ),
        r"\1[REDACTED_CONTEXT_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)(\b[a-z][a-z0-9+.-]*://(?:[^/\s:@]+):)"
            r"([^@/\s]+)(@)"
        ),
        r"\1[REDACTED_URI_PASSWORD]\3",
    ),
    (
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
        "[REDACTED_BEARER_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)(\bauthorization\s*:\s*(?:basic|token)\s+)"
            r"[^\s,;]+"
        ),
        r"\1[REDACTED_AUTH_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:access_token|refresh_token|oauth_token|id_token)"
            r"[\"']?\s*[:=]\s*)" + _ASSIGNMENT_VALUE
        ),
        r"\1[REDACTED_OAUTH_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)((?<![a-z0-9_-])[\"']?(?:session[_-]?token|handoff|token)"
            r"[\"']?\s*(?::|=|\bis\b)\s*)" + _ASSIGNMENT_VALUE
        ),
        r"\1[REDACTED_SECRET]",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:api[_-]?key|x-api-key)[\"']?\s*[:=]\s*)" + _ASSIGNMENT_VALUE
        ),
        r"\1[REDACTED_API_KEY]",
    ),
    (
        re.compile(
            r"(?i)([\"']?(?:password|passwd|pwd|client[ _-]?secret)"
            r"[\"']?\s*(?::|=|\bis\b)\s*)" + _ASSIGNMENT_VALUE
        ),
        r"\1[REDACTED_PASSWORD]",
    ),
    (
        re.compile(r"(?i)([\"']?secret[\"']?\s*[:=]\s*)" + _ASSIGNMENT_VALUE),
        r"\1[REDACTED_PASSWORD]",
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
            r"(?i)([#?&](?:access_token|approval|approval_token|api_key|apikey|"
            r"client_secret|code|handoff|id_token|key|nonce|oauth_token|password|"
            r"refresh_token|session|session_token|sig|signature|state|token)=)"
            r"[^&#\s\"']+"
        ),
        r"\1[REDACTED_SIGNED_FRAGMENT]",
    ),
)


def _apply_structural_patterns(value: str) -> str:
    redacted = value
    for pattern, replacement in _STRUCTURAL_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _redact_query_value(key: str, value: str, *, depth: int, fragment: bool) -> str:
    if key.casefold() in _URL_SECRET_KEYS:
        return "[REDACTED_SIGNED_FRAGMENT]" if fragment else "[REDACTED_OAUTH_TOKEN]"
    return _redact_nested_value(value, depth=depth + 1)


def _redact_url(match: re.Match[str], *, depth: int) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        redacted_query_pairs = [
            (
                key,
                _redact_query_value(key, value, depth=depth, fragment=False),
            )
            for key, value in query_pairs
        ]
        fragment = parts.fragment
        fragment_pairs = parse_qsl(fragment, keep_blank_values=True)
        redacted_fragment_pairs = [
            (
                key,
                _redact_query_value(key, value, depth=depth, fragment=True),
            )
            for key, value in fragment_pairs
        ]
        if (
            redacted_query_pairs == query_pairs
            and redacted_fragment_pairs == fragment_pairs
        ):
            return raw
        query = urlencode(redacted_query_pairs)
        if fragment_pairs:
            fragment = urlencode(redacted_fragment_pairs)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))
    except (TypeError, ValueError):
        return "[REDACTED_URL_WITH_SECRET]"


def _redact_nested_value(value: str, *, depth: int) -> str:
    if depth >= _MAX_NESTED_REDACTION_DEPTH:
        redacted = _apply_structural_patterns(value)
        if redacted != value:
            return redacted
        decoded = unquote(value)
        if decoded != value:
            nested = _URL.sub(lambda match: _redact_url(match, depth=depth), decoded)
            nested = _apply_structural_patterns(nested)
            if nested != decoded:
                return quote(nested, safe="")
        return value

    redacted = _URL.sub(lambda match: _redact_url(match, depth=depth), value)
    redacted = _apply_structural_patterns(redacted)
    if redacted != value:
        return redacted

    if value.startswith(("?", "#")):
        prefix, query_string = value[0], value[1:]
        pairs = parse_qsl(query_string, keep_blank_values=True)
        if pairs:
            fragment = prefix == "#"
            nested = prefix + urlencode(
                [
                    (
                        key,
                        _redact_query_value(
                            key,
                            item,
                            depth=depth,
                            fragment=fragment,
                        ),
                    )
                    for key, item in pairs
                ]
            )
            if nested != value:
                return nested

    decoded = unquote(value)
    if decoded != value:
        nested = _redact_nested_value(decoded, depth=depth + 1)
        if nested != decoded:
            return quote(nested, safe="")
    return value


def _redact_structural_secrets(value: str) -> str:
    return _redact_nested_value(value, depth=0)


def _redact_known_values(value: str, configured_secrets: Sequence[str]) -> str:
    redacted = value
    unique_secrets = {
        secret
        for secret in configured_secrets
        if isinstance(secret, str) and len(secret) >= 8
    }
    variants: set[str] = set()
    for secret in unique_secrets:
        frontier = {secret}
        variants.add(secret)
        for _depth in range(_MAX_NESTED_REDACTION_DEPTH):
            encoded = {
                candidate
                for item in frontier
                for candidate in (quote(item, safe=""), quote_plus(item, safe=""))
            }
            encoded -= variants
            if not encoded:
                break
            variants.update(encoded)
            frontier = encoded
    for variant in sorted(variants, key=len, reverse=True):
        if "%" not in variant:
            redacted = redacted.replace(variant, "[REDACTED_CONFIGURED_SECRET]")
            continue
        pieces: list[str] = []
        index = 0
        while index < len(variant):
            if (
                variant[index] == "%"
                and index + 2 < len(variant)
                and all(
                    character in "0123456789abcdefABCDEF"
                    for character in variant[index + 1 : index + 3]
                )
            ):
                first, second = variant[index + 1 : index + 3]
                pieces.append(
                    "%"
                    + (
                        f"[{first.lower()}{first.upper()}]"
                        if first.isalpha()
                        else first
                    )
                    + (
                        f"[{second.lower()}{second.upper()}]"
                        if second.isalpha()
                        else second
                    )
                )
                index += 3
                continue
            pieces.append(re.escape(variant[index]))
            index += 1
        redacted = re.sub(
            "".join(pieces),
            "[REDACTED_CONFIGURED_SECRET]",
            redacted,
        )
    return redacted


def _normalized_secret_key(value: str) -> str:
    separated_acronyms = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    separated_words = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        separated_acronyms,
    )
    return re.sub(r"[^A-Za-z0-9]+", "_", separated_words).strip("_").lower()


def _is_secret_key(value: str) -> bool:
    return bool(_SECRET_KEY.search(_normalized_secret_key(value)))


def _redact_text_value(
    value: str,
    *,
    configured_secrets: Sequence[str],
    json_depth: int,
) -> str:
    redacted = _redact_known_values(value, configured_secrets)
    redacted = _redact_structural_secrets(redacted)
    redacted = _redact_known_values(redacted, configured_secrets)
    if json_depth >= _MAX_NESTED_JSON_DEPTH:
        return redacted
    try:
        parsed = json.loads(redacted)
    except (TypeError, ValueError, json.JSONDecodeError):
        return redacted
    if not isinstance(parsed, (dict, list)):
        return redacted
    safe = _redact_json_value(
        parsed,
        configured_secrets=configured_secrets,
        json_depth=json_depth + 1,
    )
    if safe == parsed:
        return redacted
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _redact_json_value(
    value: object,
    *,
    configured_secrets: Sequence[str],
    json_depth: int,
    key: str = "",
    secret_context: bool = False,
) -> object:
    inside_secret = secret_context or bool(key and _is_secret_key(key))
    if json_depth >= _MAX_NESTED_JSON_DEPTH:
        return "[REDACTED_NESTED_CONTENT]"
    if isinstance(value, str):
        if inside_secret:
            return value if _REDACTION_MARKER.fullmatch(value) else "[REDACTED_SECRET]"
        if value.lstrip().startswith(("{", "[")):
            return _redact_text_value(
                value,
                configured_secrets=configured_secrets,
                json_depth=json_depth,
            )
        return value
    if isinstance(value, dict):
        return {
            str(item_key): _redact_json_value(
                item,
                configured_secrets=configured_secrets,
                json_depth=json_depth + 1,
                key=str(item_key),
                secret_context=inside_secret,
            )
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_json_value(
                item,
                configured_secrets=configured_secrets,
                json_depth=json_depth + 1,
                secret_context=inside_secret,
            )
            for item in value
        ]
    if inside_secret:
        return "[REDACTED_SECRET]"
    return value


def redact_content(
    value: str,
    *,
    configured_secrets: Sequence[str] = (),
) -> RedactedContent:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    normalized = unicodedata.normalize("NFC", value)
    redacted = _redact_text_value(
        normalized,
        configured_secrets=configured_secrets,
        json_depth=0,
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
