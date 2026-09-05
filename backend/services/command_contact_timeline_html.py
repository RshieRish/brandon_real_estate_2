"""Pure structural evidence from an already verified Command HTML archive.

The caller owns archive hashing and source/contact ownership checks. These facts
describe HTML boundaries only; they never modify or replace captured content.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Literal

_ACTIVITY_DATA_TESTS = frozenset(
    f"timeline-{kind}"
    for kind in (
        "note",
        "smartplans",
        "email",
        "text",
        "call",
        "source-change",
        "contact-agent",
        "schedule-virtual-tour",
        "permissions",
        "neighborhoods",
        "open-house",
        "sites",
        "collections",
        "saved-search",
        "listings",
        "task",
        "contact",
        "contact-details",
        "system",
    )
)
_FOOTER_CLASSES = frozenset(
    {"txt-p", "d-flex", "justify-content-center", "align-items-center", "pb-4"}
)
_HIDDEN_STYLE = re.compile(
    r"(?:^|;)\s*display\s*:\s*none\s*(?:!important)?\s*(?:;|$)", re.IGNORECASE
)
_TIME = re.compile(r"(?:0?[1-9]|1[0-2]):[0-5]\d [AP]M", re.IGNORECASE)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass(frozen=True, slots=True)
class TimelineHTMLHeading:
    day: date | None
    text: str
    before_event_index: int


@dataclass(frozen=True, slots=True)
class TimelineHTMLActivity:
    index: int
    data_test: str
    heading_index: int | None
    day: date | None
    text: str
    header: tuple[str, ...] = ()
    trailing_reply_button: bool = False
    canonical_lines: tuple[str, ...] = ()
    legacy_text: str | None = None
    legacy_lines: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class TimelineHTMLFacts:
    headings: tuple[TimelineHTMLHeading, ...] = ()
    activities: tuple[TimelineHTMLActivity, ...] = ()
    terminal_footer: bool = False
    complete_eof: bool = True
    terminal_boundary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveredTimelineTail:
    first_activity_index: int
    lines: tuple[str, ...]
    activity_count: int
    archive_restored: bool = False


@dataclass(slots=True)
class _Capture:
    kind: Literal["heading", "activity", "footer"]
    depth: int
    data_test: str = ""
    parts: list[str] = field(default_factory=list)
    complete: bool = True
    button_depth: int | None = None
    button_start: int = 0
    reply_button_end: int | None = None


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _day(value: str) -> date | None:
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date()  # noqa: DTZ007 - date only
        except ValueError:
            pass
    return None


class _TimelineHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[TimelineHTMLHeading] = []
        self.activities: list[TimelineHTMLActivity] = []
        self.terminal_footer = False
        self._stack: list[tuple[str, bool]] = []
        self._capture: _Capture | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        suppressed = (
            bool(self._stack and self._stack[-1][1])
            or tag in {"script", "style", "template"}
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").casefold() == "true"
            or bool(_HIDDEN_STYLE.search(attributes.get("style") or ""))
        )
        if not suppressed and self._capture and tag in _BLOCK_TAGS:
            self._capture.parts.append("\n")
        if tag in _VOID_TAGS:
            return
        self._stack.append((tag, suppressed))
        if (
            not suppressed
            and self._capture
            and self._capture.kind == "activity"
            and tag == "button"
        ):
            self._capture.button_depth = len(self._stack)
            self._capture.button_start = len(self._capture.parts)
        if suppressed or self._capture:
            return
        classes = (attributes.get("class") or "").split()
        if (
            tag == "h5"
            and "txt-h5" in classes
            and any(
                token.startswith("styles_date-header__")
                and token != "styles_date-header__"
                for token in classes
            )
        ):
            self.terminal_footer = False
            self._capture = _Capture("heading", len(self._stack))
        elif tag == "div" and attributes.get("data-test") in _ACTIVITY_DATA_TESTS:
            self.terminal_footer = False
            self._capture = _Capture(
                "activity", len(self._stack), data_test=attributes["data-test"] or ""
            )
        elif tag == "p" and set(classes) == _FOOTER_CLASSES:
            self._capture = _Capture("footer", len(self._stack))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == tag
            ),
            None,
        )
        if index is None:
            return
        if self._capture and index != len(self._stack) - 1:
            self._capture.complete = False
        if (
            self._capture
            and tag == "button"
            and self._capture.button_depth == index + 1
        ):
            capture = self._capture
            if _normalize("".join(capture.parts[capture.button_start :])) == "Reply":
                capture.reply_button_end = len(capture.parts)
            capture.button_depth = None
        if self._capture and index < self._capture.depth:
            capture = self._capture
            self._capture = None
            if index == capture.depth - 1:
                self._finish_capture(capture)
        elif self._capture and not self._stack[-1][1] and tag in _BLOCK_TAGS:
            self._capture.parts.append("\n")
        del self._stack[index:]

    def handle_data(self, data: str) -> None:
        if self._capture and not self._stack[-1][1]:
            self._capture.parts.append(data)

    def _finish_capture(self, capture: _Capture) -> None:
        raw_text = "".join(capture.parts)
        text = _normalize(raw_text)
        if capture.kind == "heading":
            self.headings.append(
                TimelineHTMLHeading(
                    _day(text) if capture.complete else None,
                    text,
                    len(self.activities),
                )
            )
        elif capture.kind == "activity" and capture.complete:
            self.activities.append(
                TimelineHTMLActivity(
                    index=len(self.activities),
                    data_test=capture.data_test,
                    heading_index=len(self.headings) - 1 if self.headings else None,
                    day=self.headings[-1].day if self.headings else None,
                    text=text,
                    header=tuple(
                        line
                        for value in raw_text.splitlines()
                        if (line := _normalize(value))
                    )[:4],
                    trailing_reply_button=(
                        capture.reply_button_end is not None
                        and not _normalize(
                            "".join(capture.parts[capture.reply_button_end :])
                        )
                    ),
                    canonical_lines=tuple(
                        line
                        for value in raw_text.splitlines()
                        if (line := _normalize(value))
                    ),
                )
            )
        elif (
            capture.kind == "footer"
            and capture.complete
            and text == "End of Timeline"
            and self.activities
        ):
            self.terminal_footer = True


def parse_timeline_html(html: str) -> TimelineHTMLFacts:
    """Read complete marked date headings and activity blocks in document order."""
    parser = _TimelineHTMLParser()
    parser.feed(html)
    parser.close()
    return TimelineHTMLFacts(
        tuple(parser.headings), tuple(parser.activities), parser.terminal_footer
    )


def match_timeline_html_event(
    facts: TimelineHTMLFacts,
    raw_lines: Sequence[str],
    *,
    start_index: int = 0,
) -> TimelineHTMLActivity | None:
    """Find one remaining compatible event, using complete content for duplicates.

    The caller advances its own cursor to ``match.index + 1`` only on success.
    Header comparison ignores casing and repeated whitespace, but not author,
    outcome, time, or kind differences. Duplicate headers require one complete
    activity text match, optionally followed by its actual next HTML heading or
    the proven final footer. A unique header still needs compatible nonempty
    body content; partial body prefixes never resolve duplicate headers.
    """
    if start_index < 0 or len(raw_lines) < 4 or isinstance(raw_lines, str | bytes):
        return None
    header = tuple(_normalize(value).casefold() for value in raw_lines[:4])
    if not all(header) or not header[3].startswith("by "):
        return None
    matches = [
        activity
        for activity in facts.activities[start_index:]
        if tuple(value.casefold() for value in activity.header) == header
    ]
    normalized_raw = _normalize(" ".join(raw_lines)).casefold()
    if len(matches) <= 1:
        if not matches:
            return None
        activity = matches[0]
        expected = activity.text.casefold()
        return (
            activity
            if (
                normalized_raw == expected
                or (
                    _normalize(" ".join(raw_lines[4:]))
                    and (
                        normalized_raw.startswith(expected + " ")
                        or expected.startswith(normalized_raw + " ")
                    )
                )
            )
            else None
        )
    complete_matches = [
        activity
        for activity in matches
        if _matches_complete_activity_text(facts, activity, normalized_raw)
        or _complete_tail_end(facts, activity.index, raw_lines) is not None
    ]
    return complete_matches[0] if len(complete_matches) == 1 else None


def _matches_complete_activity_text(
    facts: TimelineHTMLFacts,
    activity: TimelineHTMLActivity,
    normalized_raw: str,
) -> bool:
    expected = activity.text.casefold()
    if normalized_raw == expected:
        return True
    if not normalized_raw.startswith(expected + " "):
        return False
    remainder = normalized_raw[len(expected) + 1 :]
    if any(
        heading.before_event_index == activity.index + 1
        and remainder == heading.text.casefold()
        for heading in facts.headings
    ):
        return True
    return (
        facts.terminal_footer
        and activity.index == len(facts.activities) - 1
        and (remainder == "end of timeline" or remainder.startswith("end of timeline "))
    )


def verified_timeline_tail_lines(
    facts: TimelineHTMLFacts,
    activity: TimelineHTMLActivity,
    raw_lines: Sequence[str],
) -> list[str] | None:
    """Trim a proven footer after one or more complete, source-owned activities.

    Legacy captures sometimes combined several activity types into one row. All
    remaining activity text and intervening headings must match before a footer
    can be removed. Returned lines retain their original content and whitespace;
    the caller remains responsible for protecting later edits and source ownership.
    """
    if (
        not (facts.terminal_footer or facts.terminal_boundary)
        or isinstance(raw_lines, str | bytes)
        or len(raw_lines) < 5
        or not 0 <= activity.index < len(facts.activities)
        or facts.activities[activity.index] != activity
    ):
        return None
    end = _complete_tail_end(facts, activity.index, raw_lines, allow_eof=False)
    return list(raw_lines[:end]) if end is not None else None


def verified_timeline_fragment_tail_lines(
    facts: TimelineHTMLFacts,
    raw_lines: Sequence[str],
) -> list[str] | None:
    """Remove controls only after an exact, complete structural body suffix.

    Old scalar extraction could split a note at a title such as ``Call``. Such a
    fragment must never acquire an activity identity or date. Its complete text
    can nevertheless prove a cleanup boundary when it starts at an actual body
    line and includes every later activity and intervening date heading through
    the verified external footer/panel. Only the known legacy scalar projection
    is an alternative to canonical text; arbitrary omissions are not accepted.

    Returned lines are unchanged. Ownership and later-edit guards remain the
    caller's responsibility; this result must not advance an activity cursor.
    """
    if (
        not (facts.terminal_footer or facts.terminal_boundary)
        or isinstance(raw_lines, str | bytes)
        or not raw_lines
        or not _normalize(raw_lines[0])
    ):
        return None
    first_line = _normalize(raw_lines[0]).casefold()
    ends: set[int] = set()
    for use_legacy, projected in (
        (False, facts),
        (True, timeline_legacy_projection(facts)),
    ):
        for activity in projected.activities:
            lines = (
                activity.legacy_lines
                if use_legacy and activity.legacy_lines is not None
                else activity.canonical_lines
            )
            if (
                not activity.header
                or _normalize(" ".join(lines)).casefold() != activity.text.casefold()
            ):
                continue
            for offset in range(len(activity.header), len(lines)):
                if _normalize(lines[offset]).casefold() != first_line:
                    continue
                suffix = replace(activity, text=_normalize(" ".join(lines[offset:])))
                suffix_facts = replace(
                    projected,
                    activities=(
                        *projected.activities[: activity.index],
                        suffix,
                        *projected.activities[activity.index + 1 :],
                    ),
                )
                end = _complete_tail_end(
                    suffix_facts, activity.index, raw_lines, allow_eof=False
                )
                if end is not None:
                    ends.add(end)
    return list(raw_lines[: ends.pop()]) if len(ends) == 1 else None


def _complete_tail_end(
    facts: TimelineHTMLFacts,
    activity_index: int,
    raw_lines: Sequence[str],
    *,
    allow_eof: bool = True,
) -> int | None:
    expected = _structural_span_text(facts, activity_index, len(facts.activities))
    if not expected or any(
        heading.before_event_index >= len(facts.activities)
        for heading in facts.headings
    ):
        return None
    for index, line in enumerate(raw_lines):
        if (
            (facts.terminal_footer and _normalize(line).casefold() == "end of timeline")
            or (
                facts.terminal_boundary
                and tuple(
                    _normalize(value).casefold()
                    for value in raw_lines[index : index + len(facts.terminal_boundary)]
                )
                == tuple(value.casefold() for value in facts.terminal_boundary)
            )
        ) and _normalize(" ".join(raw_lines[:index])).casefold() == expected:
            return index
    if (
        allow_eof
        and facts.complete_eof
        and _normalize(" ".join(raw_lines)).casefold() == expected
    ):
        return len(raw_lines)
    return None


def _structural_span_text(
    facts: TimelineHTMLFacts, start_index: int, stop_index: int
) -> str:
    segments: list[str] = []
    for index in range(start_index, stop_index):
        if index > start_index:
            segments.extend(
                heading.text
                for heading in facts.headings
                if heading.before_event_index == index
            )
        segments.append(facts.activities[index].text)
    return _normalize(" ".join(segments)).casefold()


def recover_timeline_navigation_tail(
    facts: TimelineHTMLFacts,
    raw_lines: Sequence[str],
) -> RecoveredTimelineTail | None:
    """Recover only a complete, structurally bounded navigation activity group.

    Start at the first possible activity header after the navigation summary,
    never skip contradictory activity content, and require exactly one complete
    sequence through footer/EOF or an actual next-date heading. Every returned
    line is the original source line. An
    initial date heading is supplied by the first activity's structural facts;
    all intervening headings remain in the returned group.
    """
    if isinstance(raw_lines, str | bytes) or len(raw_lines) < 4 or not facts.activities:
        return None
    lower = [_normalize(line).casefold() for line in raw_lines]
    if not (
        lower[0] == "smartplans"
        and lower[1 if not lower[1].isdigit() else 2] == "tasks"
        and all(
            marker in lower
            for marker in (
                "notes",
                "saved searches",
                "all time",
                "all activity",
                "ai summary",
            )
        )
    ):
        return None
    summary_index = lower.index("ai summary")
    start = next(
        (
            index
            for index in range(summary_index + 1, len(lower) - 2)
            if lower[index] and _TIME.fullmatch(lower[index + 1]) and lower[index + 2]
        ),
        None,
    )
    if start is None:
        return None
    matches: list[RecoveredTimelineTail] = []
    for activity in facts.activities:
        width = min(3, len(activity.header))
        if width < 2 or tuple(
            value.casefold() for value in activity.header[:width]
        ) != tuple(lower[start : start + width]):
            continue
        end = _complete_tail_end(facts, activity.index, raw_lines[start:])
        if end is not None:
            matches.append(
                RecoveredTimelineTail(
                    activity.index,
                    tuple(raw_lines[start : start + end]),
                    len(facts.activities) - activity.index,
                )
            )
        for heading in facts.headings:
            stop_index = heading.before_event_index
            if not (
                activity.index < stop_index < len(facts.activities)
                and lower[-1] == heading.text.casefold()
                and sum(
                    item.before_event_index == stop_index for item in facts.headings
                )
                == 1
            ):
                continue
            if _normalize(
                " ".join(raw_lines[start:-1])
            ).casefold() == _structural_span_text(facts, activity.index, stop_index):
                matches.append(
                    RecoveredTimelineTail(
                        activity.index,
                        tuple(raw_lines[start:-1]),
                        stop_index - activity.index,
                    )
                )
    return matches[0] if len(matches) == 1 else None


def recover_timeline_navigation_archive_tail(
    facts: TimelineHTMLFacts,
    raw_lines: Sequence[str],
) -> RecoveredTimelineTail | None:
    """Restore an archive group only through its exact known legacy projection.

    Snapshot facts may identify quoted generic body values that the old scalar
    reader omitted entirely. No other omission or content mismatch is allowed.
    The caller must verify archive/source ownership and protect subsequent edits;
    returned canonical lines are explicit archive-backed presentation, not a
    claim that the raw source already contained the restored text.
    """
    projected = timeline_legacy_projection(facts)
    recovered = recover_timeline_navigation_tail(projected, raw_lines)
    if recovered is None:
        return None
    selected = facts.activities[
        recovered.first_activity_index : recovered.first_activity_index
        + recovered.activity_count
    ]
    if not any(activity.legacy_text is not None for activity in selected) or any(
        not activity.canonical_lines for activity in selected
    ):
        return None
    canonical: list[str] = []
    for activity in selected:
        if activity.index > recovered.first_activity_index:
            canonical.extend(
                heading.text
                for heading in facts.headings
                if heading.before_event_index == activity.index
            )
        canonical.extend(activity.canonical_lines)
    return RecoveredTimelineTail(
        recovered.first_activity_index,
        tuple(canonical),
        recovered.activity_count,
        archive_restored=True,
    )


def timeline_legacy_projection(facts: TimelineHTMLFacts) -> TimelineHTMLFacts:
    """Change only activity text to the proven old quoted-generic projection."""
    return replace(
        facts,
        activities=tuple(
            replace(activity, text=activity.legacy_text)
            if activity.legacy_text is not None
            else activity
            for activity in facts.activities
        ),
    )
