"""Conservative presentation of captured Command profile/timeline content."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

_US_REGIONS = frozenset(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
    ]
)
_LOCALITY = re.compile(r"^([^,\n]+),\s*([A-Z]{2}),(?:\s*US,)?\s*(\d{5}(?:-\d{4})?)$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", re.IGNORECASE)
_DATE = re.compile(r"^[A-Za-z]{3,9} \d{1,2}, \d{4}$")
_KINDS = frozenset({"CALL", "EMAIL", "TEXT", "SMARTPLANS", "NOTE", "SYSTEM", "CONTACT"})


@dataclass(frozen=True)
class CapturedMailingAddress:
    formatted: str
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


@dataclass(frozen=True)
class CapturedTimeline:
    hidden: bool = False
    title: str | None = None
    body: str | None = None
    captured_date: date | None = None
    captured_time: str | None = None
    next_date: date | None = None
    recognized: bool = False
    outcome: str | None = None
    kind: str | None = None


def source_raw_lines(payload_json: str) -> list[str] | None:
    try:
        payload = json.loads(payload_json)
        values = payload.get("values") if isinstance(payload, dict) else None
        lines = values.get("raw_lines") if isinstance(values, dict) else None
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(lines, list)
        or not lines
        or not all(isinstance(line, str) for line in lines)
    ):
        return None
    return lines


def capture_coordinates_match(
    payload_json: str,
    *,
    source_contact_id: str,
    capture_ordinal: int,
    occurrence_ordinal: int,
) -> bool:
    """Require the immutable parser coordinates to agree with the owned row chain."""
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    captured = payload.get("capture_ordinal")
    if isinstance(captured, str) and re.fullmatch(r"[0-9]{7}", captured):
        captured = int(captured)
    return (
        re.fullmatch(r"[0-9a-f]{24}", source_contact_id) is not None
        and payload.get("source_contact_id") == source_contact_id
        and type(captured) is int
        and captured > 0
        and captured == capture_ordinal
        and payload.get("section_name") == "timeline"
        and type(payload.get("occurrence_ordinal")) is int
        and payload["occurrence_ordinal"] > 0
        and payload["occurrence_ordinal"] == occurrence_ordinal
    )


def _profile(lines: list[str]) -> bool:
    labels = [line.casefold() for line in lines]
    required = [
        "email",
        "phone",
        "home address",
        "mailing address",
        "legal name",
        "social profiles",
        "about",
        "description",
        "timeline",
        "opportunities",
    ]
    if not labels or labels[0] != "email":
        return False
    positions = [labels.index(label) if label in labels else -1 for label in required]
    return -1 not in positions and positions == sorted(positions)


def _date(value: str) -> date | None:
    if not _DATE.fullmatch(value):
        return None
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date()  # noqa: DTZ007 - source date only
        except ValueError:
            pass
    return None


def _without_footer(content: list[str]) -> list[str]:
    for index, value in enumerate(content):
        rest = content[index + 1 :]
        following = [
            line for line in rest[:4] if not re.fullmatch(r"[\ue000-\uf8ff]+", line)
        ]
        end_footer = (
            value == "End of Timeline"
            and len(following) >= 2
            and following[0] == "Welcome to KWIQ"
            and following[1].startswith("KWIQ uses artificial intelligence (AI).")
        )
        ai_footer = value == "Welcome to KWIQ" and any(
            line.startswith("KWIQ uses artificial intelligence (AI).")
            for line in rest[:2]
        )
        if end_footer or ai_footer:
            return content[:index]
    return content


def read_mailing_address(lines: list[str]) -> CapturedMailingAddress | None:
    if not _profile(lines):
        return None
    labels = [line.casefold() for line in lines]
    address = [
        line.strip()
        for line in lines[
            labels.index("mailing address") + 1 : labels.index("legal name")
        ]
        if line.strip()
    ]
    if not address or all(
        line.casefold() in {"--", "—", "n/a", "none"} for line in address
    ):
        return None
    formatted = "\n".join(address)
    locality = _LOCALITY.fullmatch(address[-1])
    # Retain incomplete/unrecognized text for review; it is not mail-ready.
    if (
        not locality
        or locality[2] not in _US_REGIONS
        or not 2 <= len(address) <= 3
        or not re.match(r"^(?:\d|P\.?\s*O\.?\s+BOX\b)", address[0], re.IGNORECASE)
    ):
        return CapturedMailingAddress(formatted=formatted)
    return CapturedMailingAddress(
        formatted=formatted,
        line1=address[0],
        line2=address[1] if len(address) == 3 else None,
        city=locality[1].strip(),
        state=locality[2],
        postal_code=locality[3],
    )


def read_timeline_capture(
    lines: list[str],
    current_date: date | None,
    *,
    has_following_event: bool = False,
    verified_activity: bool = False,
) -> CapturedTimeline:
    if _profile(lines):
        return CapturedTimeline(hidden=True, recognized=True, next_date=None)
    lower = [line.casefold() for line in lines]
    navigation = (
        bool(lower)
        and lower[0] == "smartplans"
        and len(lower) > 2
        and lower[1 if not lower[1].isdigit() else 2] == "tasks"
        and all(
            value in lower
            for value in (
                "notes",
                "saved searches",
                "all time",
                "all activity",
                "ai summary",
            )
        )
    )
    if navigation:
        return CapturedTimeline(
            hidden=True, recognized=True, next_date=_date(lines[-1])
        )
    time_match = _TIME.fullmatch(lines[1]) if len(lines) > 1 else None
    if (
        len(lines) < 4
        or lines[0].upper() not in _KINDS
        or not time_match
        or not lines[3].startswith("By ")
    ):
        content = list(lines) if verified_activity else _without_footer(lines)
        return CapturedTimeline(
            body="\n".join(content), next_date=None, recognized=content != lines
        )
    try:
        local_time = datetime.strptime(lines[1], "%I:%M %p").strftime("%H:%M:%S")  # noqa: DTZ007 - captured wall clock
    except ValueError:
        return CapturedTimeline(body="\n".join(lines), next_date=None)
    content = list(lines[4:]) if verified_activity else _without_footer(list(lines[4:]))
    next_date = current_date
    if (
        has_following_event
        and content == lines[4:]
        and content
        and (following_day := _date(content[-1])) is not None
    ):
        next_date = following_day
        content.pop()
    title = content[0] if content else lines[0].title()
    body = "\n".join(content[1:]) or None
    return CapturedTimeline(
        title=title,
        body=body,
        captured_date=current_date,
        captured_time=local_time,
        next_date=next_date,
        recognized=True,
        outcome=lines[2],
    )


def is_captured_event_header(lines: list[str] | None) -> bool:
    return bool(
        lines
        and len(lines) >= 4
        and lines[0].upper() in _KINDS
        and _TIME.fullmatch(lines[1])
        and lines[3].startswith("By ")
    )


def has_embedded_timeline_activity(lines: list[str]) -> bool:
    """An unclassified activity-shaped capture must never become a false empty."""
    lower = [line.casefold() for line in lines]
    if "ai summary" not in lower:
        return False
    start = lower.index("ai summary") + 1
    return any(
        bool(lines[index - 1].strip()) and _TIME.fullmatch(lines[index].strip())
        for index in range(start + 1, len(lines))
    )
