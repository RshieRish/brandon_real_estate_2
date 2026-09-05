"""Pure timeline evidence from an already verified accessibility snapshot.

Archive/source ownership is the caller's responsibility. Snapshot roles and
outline depth establish boundaries; date-like plain text never establishes one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from unicodedata import category

from services.command_contact_timeline_html import (
    TimelineHTMLActivity,
    TimelineHTMLFacts,
    TimelineHTMLHeading,
)

_KINDS = frozenset(
    {
        "call",
        "email",
        "text",
        "smartplans",
        "note",
        "system",
        "contact",
        "contact details",
        "source change",
        "source",
        "neighborhoods",
        "open house",
        "agent site",
        "collection",
        "saved search",
        "listing",
        "task",
    }
)
_AUTOMATED_KINDS = frozenset(
    {
        "source",
        "property inquiry",
        "listing",
        "collection",
        "saved search",
        "agent site",
        "client inquiry",
        "in person tour",
        "home valuation request",
        "google calendar invite",
        "info",
    }
)
_TWO_FIELD_KINDS = frozenset({"property inquiry", "google calendar invite"})
_TIME = re.compile(r"(?:0?[1-9]|1[0-2]):[0-5]\d [AP]M", re.IGNORECASE)
_SCALAR = re.compile(r"^( *)- (generic|paragraph|text|strong):\s*(.*)$")
_NAMED = re.compile(r'^( *)- (heading|link|button|cell) "([^"]+)"(.*)$')
_LEGACY_GENERIC = re.compile(r'- generic:\s*"?([^"\n]+)"?$')


@dataclass(frozen=True, slots=True)
class _Line:
    indent: int
    role: str
    text: str = ""
    level: int | None = None
    legacy_omitted: bool = False


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _line(value: str) -> _Line:
    """Match legacy snapshot scalar/name values without discarding their roles."""
    if match := _SCALAR.fullmatch(value):
        text = match[3].strip()
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return _Line(
            len(match[1]),
            match[2],
            _normalize(text),
            legacy_omitted=(
                match[2] == "generic"
                and '"' in text
                and _LEGACY_GENERIC.fullmatch(value.strip()) is None
            ),
        )
    if match := _NAMED.fullmatch(value):
        level = re.fullmatch(r" \[level=(\d+)\]:?", match[4])
        return _Line(
            len(match[1]),
            match[2],
            _normalize(match[3]),
            int(level[1]) if level and match[2] == "heading" else None,
        )
    stripped = value.strip()
    if stripped in {"- separator", "- button", "- checkbox"}:
        return _Line(len(value) - len(value.lstrip()), stripped[2:])
    return _Line(
        len(value) - len(value.lstrip()),
        "",
        "" if stripped.startswith(("- ", "/url:")) else _normalize(stripped),
    )


def _day(value: str) -> date | None:
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date()  # noqa: DTZ007 - date only
        except ValueError:
            pass
    return None


def _header(lines: list[_Line], index: int, indent: int) -> tuple[str, ...]:
    values = _generic_fields(lines, index, indent, 4)
    if values and (
        values[0].casefold() in _KINDS | _AUTOMATED_KINDS
        and _TIME.fullmatch(values[1])
        and values[3].casefold().startswith("by ")
    ):
        return values
    for width, kinds in ((3, _AUTOMATED_KINDS), (2, _TWO_FIELD_KINDS)):
        values = _generic_fields(lines, index, indent, width)
        if (
            not values
            or values[0].casefold() not in kinds
            or not _TIME.fullmatch(values[1])
        ):
            continue
        next_index = index + width
        if next_index >= len(lines):
            continue
        boundary = lines[next_index]
        if boundary.indent != indent:
            continue
        if boundary.role == "separator":
            if next_index + 1 < len(lines):
                body = lines[next_index + 1]
                if body.indent >= indent and body.text:
                    return values
        elif (
            width == 3
            and values[0].casefold() == "agent site"
            and _structural_boundary(lines, next_index, indent)
        ):
            return values
    return ()


def _generic_fields(
    lines: list[_Line], index: int, indent: int, width: int
) -> tuple[str, ...]:
    fields = lines[index : index + width]
    if len(fields) != width or any(
        item.role != "generic"
        or item.indent != indent
        or not item.text
        or item.legacy_omitted
        for item in fields
    ):
        return ()
    return tuple(item.text for item in fields)


def _structural_boundary(lines: list[_Line], index: int, indent: int) -> bool:
    item = lines[index]
    if item.indent != indent:
        return False
    if (item.role == "heading" and item.level == 5) or (
        item.role == "paragraph" and item.text == "End of Timeline"
    ):
        return True
    fields = _generic_fields(lines, index, indent, 4)
    if (
        fields
        and fields[0].casefold() in _KINDS | _AUTOMATED_KINDS
        and (_TIME.fullmatch(fields[1]) and fields[3].casefold().startswith("by "))
    ):
        return True
    fields = _generic_fields(lines, index, indent, 3)
    return bool(
        fields
        and fields[0].casefold() in _AUTOMATED_KINDS
        and _TIME.fullmatch(fields[1])
    )


def _external_consent_boundary(
    lines: list[_Line], index: int, indent: int
) -> tuple[str, ...]:
    """Recognize the complete external consent-panel role sequence, not its words."""
    first = lines[index]
    if not (
        first.indent == indent
        and first.role == "generic"
        and len(first.text) == 1
        and category(first.text) == "Co"
    ):
        return ()
    core = [
        (position, item)
        for position, item in enumerate(lines[index : index + 28], index)
        if item.indent == indent and (item.text or item.role in {"button", "checkbox"})
    ][:12]
    if len(core) != 12:
        return ()
    items = [item for _, item in core]
    if [item.role for item in items] != [
        "generic",
        "generic",
        "button",
        "text",
        "text",
        "link",
        "text",
        "link",
        "text",
        "checkbox",
        "button",
        "button",
    ]:
        return ()
    if not (
        items[1].text == "Welcome to KWIQ"
        and not items[2].text
        and items[3].text.startswith("KWIQ uses artificial intelligence (AI)")
        and items[4].text.startswith("By ")
        and items[5].text == "Terms of Use"
        and items[7].text == "Privacy Policy"
        and not items[9].text
        and items[10].text == "Accept"
        and items[11].text == "Cancel"
    ):
        return ()
    for position in range(core[-1][0] + 1, len(lines)):
        later = lines[position]
        if later.indent == indent and later.role == "heading" and later.level == 5:
            return ()
        pair = _generic_fields(lines, position, indent, 2)
        if pair and _TIME.fullmatch(pair[1]):
            return ()
    return first.text, items[1].text


def _footer_has_no_following_body(lines: list[_Line], index: int, indent: int) -> bool:
    following = next(
        (position for position in range(index + 1, len(lines)) if lines[position].text),
        None,
    )
    return (
        following is None
        or bool(_external_consent_boundary(lines, following, indent))
        or _external_notifications_panel(lines, following, indent)
    )


def _external_notifications_panel(lines: list[_Line], index: int, indent: int) -> bool:
    """Prove the observed empty Notifications/Help panel after an actual footer.

    Labels alone are insufficient: the complete outline requires two heading
    levels, an icon link with its nested child, all notification tab/empty-state
    roles, and the Help control. This is not a standalone timeline boundary.
    """
    core = [
        (position, item)
        for position, item in enumerate(lines[index : index + 28], index)
        if item.indent == indent and (item.text or item.role == "button")
    ][:15]
    if len(core) != 15:
        return False
    items = [item for _, item in core]
    if [item.role for item in items] != [
        "generic",
        "heading",
        "link",
        "generic",
        "generic",
        "generic",
        "generic",
        "text",
        "generic",
        "generic",
        "generic",
        "generic",
        "heading",
        "generic",
        "button",
    ]:
        return False
    if not (
        all(
            len(items[offset].text) == 1 and category(items[offset].text) == "Co"
            for offset in (0, 2, 3, 8, 9, 13)
        )
        and items[1].level == 2
        and items[1].text == "Notifications"
        and [items[offset].text for offset in (4, 5, 6, 7, 10, 11)]
        == [
            "Unread",
            "Read",
            "0 Unread",
            "All Notifications",
            "You don’t have any unread notifications.",
            "Mark All as Read",
        ]
        and items[12].level == 3
        and items[12].text == "Help & Information"
        and not items[14].text
    ):
        return False
    visible_outline = [
        item for item in lines[index : core[-1][0] + 1] if item.text or item.role
    ]
    if visible_outline != [
        *items[:3],
        _Line(indent + 2, "generic", items[2].text),
        *items[3:],
    ]:
        return False
    for position in range(core[-1][0] + 1, len(lines)):
        later = lines[position]
        if later.indent == indent and later.role == "heading" and later.level == 5:
            return False
        pair = _generic_fields(lines, position, indent, 2)
        if pair and _TIME.fullmatch(pair[1]):
            return False
    return True


def parse_timeline_snapshot(snapshot: str) -> TimelineHTMLFacts:
    """Recover complete activity headers and role-proven dates/footer in order."""
    lines = [_line(value) for value in snapshot.splitlines() if value.strip()]
    headings: list[TimelineHTMLHeading] = []
    activities: list[TimelineHTMLActivity] = []
    context_indent: int | None = None
    event_heading_index: int | None = None
    header: tuple[str, ...] = ()
    content: list[str] = []
    legacy_content: list[str] = []
    has_legacy_omission = False
    terminal_footer = False
    terminal_boundary: tuple[str, ...] = ()
    trailing_reply_button = False

    def finish_activity() -> None:
        nonlocal \
            header, \
            content, \
            trailing_reply_button, \
            legacy_content, \
            has_legacy_omission
        if not header:
            return
        activities.append(
            TimelineHTMLActivity(
                index=len(activities),
                data_test="timeline-" + header[0].casefold().replace(" ", "-"),
                heading_index=event_heading_index,
                day=headings[event_heading_index].day
                if event_heading_index is not None
                else None,
                text=" ".join(content),
                header=header,
                trailing_reply_button=trailing_reply_button,
                canonical_lines=tuple(content),
                legacy_text=" ".join(legacy_content) if has_legacy_omission else None,
                legacy_lines=tuple(legacy_content) if has_legacy_omission else None,
            )
        )
        header, content = (), []
        legacy_content, has_legacy_omission = [], False
        trailing_reply_button = False

    index = 0
    while index < len(lines):
        item = lines[index]
        if context_indent is None:
            if item.role == "generic" and item.text == "AI Summary":
                context_indent = item.indent
            index += 1
            continue
        if item.indent < context_indent:
            if not header and not activities:
                headings.clear()
                context_indent = None
                continue
            break
        if item.indent == context_indent and item.role == "heading" and item.level == 5:
            finish_activity()
            headings.append(
                TimelineHTMLHeading(_day(item.text), item.text, len(activities))
            )
        elif fields := _header(lines, index, context_indent):
            finish_activity()
            header = fields
            content = list(fields)
            legacy_content = list(fields)
            event_heading_index = len(headings) - 1 if headings else None
            index += len(fields)
            continue
        elif (
            header
            and item.indent == context_indent
            and item.role == "paragraph"
            and item.text == "End of Timeline"
            and _footer_has_no_following_body(lines, index, context_indent)
            and not any(
                (
                    later.indent == context_indent
                    and (
                        (later.role == "heading" and later.level == 5)
                        or (
                            later.role == "paragraph"
                            and later.text == "End of Timeline"
                        )
                    )
                )
                or _header(lines, later_index, context_indent)
                for later_index, later in enumerate(lines[index + 1 :], index + 1)
            )
        ):
            terminal_footer = True
            break
        elif header and (
            boundary := _external_consent_boundary(lines, index, context_indent)
        ):
            terminal_boundary = boundary
            break
        elif header and item.text:
            content.append(item.text)
            if item.legacy_omitted:
                has_legacy_omission = True
            else:
                legacy_content.append(item.text)
            trailing_reply_button = item.role == "button" and item.text == "Reply"
        index += 1
    finish_activity()
    return TimelineHTMLFacts(
        tuple(headings),
        tuple(activities),
        terminal_footer,
        # A flat outline can continue into sitewide controls after the last
        # activity. Only an actual footer/next heading bounds that activity.
        complete_eof=False,
        terminal_boundary=terminal_boundary,
    )
