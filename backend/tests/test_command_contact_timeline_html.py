"""HTML structure, not note wording, establishes captured timeline boundaries."""

from datetime import date

import pytest


def heading(text: str, *, suffix: str = "uUkXK") -> str:
    return f'<h5 class="txt-h5 styles_date-header__{suffix}">{text}</h5>'


def activity(body: str, *, kind: str = "note", time: str = "9:15 AM") -> str:
    return (
        f'<div class="d-flex my-3 ml-2" data-test="timeline-{kind}">'
        f"<div>{kind.title()}</div><div>{time}</div><div>Created</div>"
        "<div>By <span>Example&nbsp;<strong>Agent</strong></span></div>"
        f"<div>{body}</div></div>"
    )


def test_actual_heading_dates_apply_to_ordered_events_not_profile_or_note_dates():
    from services.command_contact_timeline_html import parse_timeline_html

    html = (
        '<p id="birthday" data-test="subsection-text">May 1, 1990</p>'
        '<p id="homeAnniversary">April 29, 2022</p>'
        "<h5>Jan 1, 2026</h5>"
        + heading("Mar 6, 2023")
        + activity("Closing appointment<p>Mar 1, 2023</p>")
        + activity("Another event", time="8:15 AM")
        + heading("February 28, 2023", suffix="next-Build42")
        + activity("Older event")
    )

    facts = parse_timeline_html(html)

    assert [(item.day, item.before_event_index) for item in facts.headings] == [
        (date(2023, 3, 6), 0),
        (date(2023, 2, 28), 2),
    ]
    assert [item.index for item in facts.activities] == [0, 1, 2]
    assert [item.heading_index for item in facts.activities] == [0, 0, 1]
    assert [item.day for item in facts.activities] == [
        date(2023, 3, 6),
        date(2023, 3, 6),
        date(2023, 2, 28),
    ]
    assert facts.activities[0].text == (
        "Note 9:15 AM Created By Example Agent Closing appointment Mar 1, 2023"
    )


def test_visible_event_text_preserves_inline_words_entities_and_block_spacing():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity(
            "Fol<strong>low</strong>-up &amp; review<br>Tomorrow"
            "<script>bad_script()</script><style>.bad { color: red }</style>"
        )
    )

    assert facts.activities[0].text == (
        "Note 9:15 AM Created By Example Agent Follow-up & review Tomorrow"
    )


def test_nested_note_markup_never_becomes_a_new_event_or_date_heading():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Quoted markup" + heading("Jan 1, 2000") + activity("Nested"))
        + activity("Second real event")
    )

    assert len(facts.activities) == 2
    assert len(facts.headings) == 1
    assert facts.activities[1].day == date(2023, 3, 6)
    assert "Quoted markup Jan 1, 2000" in facts.activities[0].text


@pytest.mark.parametrize(
    "kind",
    [
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
    ],
)
def test_other_activity_types_preserve_html_order_and_navigation_is_excluded(kind):
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        '<div data-test="timeline-tab">Timeline</div>'
        + heading("Mar 6, 2023")
        + activity("First", kind=kind)
        + activity("Second")
        + '<div data-test="timeline-neighborhood-url">A control</div>'
    )

    assert [item.data_test for item in facts.activities] == [
        f"timeline-{kind}",
        "timeline-note",
    ]
    assert [item.index for item in facts.activities] == [0, 1]


FOOTER_CLASSES = "txt-p d-flex justify-content-center align-items-center pb-4"


def footer(text: str = "End of Timeline", *, classes: str = FOOTER_CLASSES) -> str:
    return f'<p class="{classes}">{text}</p>'


def test_footer_requires_a_complete_structural_paragraph_after_the_events():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("The note")
        + footer()
        + "<aside><p>Welcome to KWIQ</p></aside>"
    )

    assert facts.terminal_footer is True
    assert "End of Timeline" not in facts.activities[0].text


@pytest.mark.parametrize(
    "html",
    [
        footer(),
        footer() + activity("After an early footer"),
        activity("Before") + footer() + activity("After"),
        activity("Before") + footer() + heading("Feb 1, 2023"),
        activity(footer()),
        activity("Before") + footer(classes="txt-p"),
        activity("Before") + footer(classes=FOOTER_CLASSES.replace("pb-4", "pb-40")),
        activity("Before") + footer("Discuss End of Timeline"),
        activity("Before") + footer().replace("<p ", "<div ").replace("</p>", "</div>"),
        activity("Before") + footer().removesuffix("</p>"),
    ],
)
def test_note_phrases_and_nonterminal_or_unproven_footers_are_not_footer_evidence(html):
    from services.command_contact_timeline_html import parse_timeline_html

    assert parse_timeline_html(html).terminal_footer is False


def test_match_uses_all_four_normalized_header_fields_with_inline_author_text():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("A note")
        + heading("Feb 1, 2023")
        + activity("An email", kind="email")
    )
    lines = ["EMAIL", " 9:15  AM ", "CREATED", "By Example\u00a0Agent", "An email"]

    match = match_timeline_html_event(facts, lines)

    assert match == facts.activities[1]
    assert match.day == date(2023, 2, 1)
    assert match.header == ("Email", "9:15 AM", "Created", "By Example Agent")
    assert lines[-1] == "An email"
    assert match_timeline_html_event(facts, lines, start_index=2) is None


def test_match_never_guesses_between_duplicate_headers_or_matches_author_prefix():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First")
        + heading("Feb 1, 2023")
        + activity("Second")
    )
    lines = ["NOTE", "9:15 AM", "Created", "By Example Agent"]

    assert match_timeline_html_event(facts, lines) is None
    assert match_timeline_html_event(facts, lines, start_index=1) is None
    assert (
        match_timeline_html_event(facts, lines + ["Second"], start_index=1)
        == facts.activities[1]
    )
    longer_author = parse_timeline_html(
        activity("A note").replace("Agent</strong>", "Agent Two</strong>")
    )
    assert match_timeline_html_event(longer_author, lines) is None


@pytest.mark.parametrize(
    "lines",
    [
        [],
        ["NOTE", "9:15 AM", "Created"],
        ["NOTE", "9:15 AM", "Updated", "By Example Agent"],
        ["EMAIL", "9:15 AM", "Created", "By Example Agent"],
        ["NOTE", "9:16 AM", "Created", "By Example Agent"],
        ["NOTE", "9:15 AM", "Created", "By A Different Agent"],
        ["NOTE", "", "", ""],
    ],
)
def test_incomplete_or_mismatching_raw_headers_stay_unknown(lines):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    assert (
        match_timeline_html_event(parse_timeline_html(activity("A note")), lines)
        is None
    )


@pytest.mark.parametrize(
    "wrapper",
    [
        "<template>{}</template>",
        "<div hidden>{}</div>",
        '<div aria-hidden="true">{}</div>',
        '<div style="display: none !important">{}</div>',
    ],
)
def test_hidden_markup_does_not_create_dates_activities_or_footer_evidence(wrapper):
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        wrapper.format(heading("Jan 1, 2000") + activity("Hidden"))
        + activity("Visible without a date")
        + wrapper.format(footer())
    )

    assert len(facts.activities) == 1
    assert facts.activities[0].day is None
    assert facts.headings == ()
    assert facts.terminal_footer is False


def test_invalid_actual_heading_resets_date_instead_of_reusing_previous_day():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Dated")
        + heading("Feb 30, 2023")
        + activity("Unknown date")
    )

    assert [item.day for item in facts.activities] == [date(2023, 3, 6), None]
    assert facts.headings[1].day is None


def test_incomplete_structural_elements_cannot_supply_dates_events_or_footer():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Dated")
        + heading("Jan 1, 2000<span>")
        + activity("Unknown date")
        + footer("End of Timeline<span>")
    )

    assert facts.activities[1].day is None
    assert facts.terminal_footer is False
    assert parse_timeline_html(activity("Unclosed<span>")).activities == ()
    assert (
        parse_timeline_html(activity("Truncated").removesuffix("</div>")).activities
        == ()
    )


@pytest.mark.parametrize("suffix", ["", " "])
def test_date_header_requires_a_real_hashed_class_suffix(suffix):
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023", suffix=suffix) + activity("A note")
    )

    assert facts.headings == ()
    assert facts.activities[0].day is None


def raw_note(*content: str) -> list[str]:
    return ["NOTE", "9:15 AM", "Created", "By Example Agent", *content]


@pytest.mark.parametrize("index", [0, 1])
def test_duplicate_metadata_is_resolved_only_by_one_complete_matching_body(index):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First complete body")
        + heading("Feb 1, 2023")
        + activity("Second complete body")
    )
    lines = raw_note("First complete body" if index == 0 else "Second complete body")

    assert match_timeline_html_event(facts, lines) == facts.activities[index]


def test_identical_metadata_and_complete_bodies_remain_ambiguous():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Same complete body")
        + heading("Feb 1, 2023")
        + activity("Same complete body")
    )

    assert match_timeline_html_event(facts, raw_note("Same complete body")) is None


@pytest.mark.parametrize("body", ["Common prefix", "Common prefix one unproven tail"])
def test_short_or_partial_body_prefix_cannot_resolve_duplicate_metadata(body):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Common prefix one")
        + heading("Feb 1, 2023")
        + activity("Common prefix two")
    )

    assert match_timeline_html_event(facts, raw_note(body)) is None


def test_complete_body_plus_the_actual_next_heading_resolves_duplicate_metadata():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First complete body")
        + heading("Feb 1, 2023")
        + activity("Second complete body")
    )
    lines = raw_note("First complete body", "FEB 1, 2023")
    original = list(lines)

    assert match_timeline_html_event(facts, lines) == facts.activities[0]
    assert lines == original


@pytest.mark.parametrize("tail", ["Jan 1, 2000", "FEB 1, 2023 Other content"])
def test_unproven_date_or_additional_body_after_next_heading_stays_unknown(tail):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First complete body")
        + heading("Feb 1, 2023")
        + activity("Second complete body")
    )

    assert (
        match_timeline_html_event(facts, raw_note("First complete body", tail)) is None
    )


@pytest.mark.parametrize(
    "tail",
    [
        ["End of Timeline"],
        ["End of Timeline", "\ue90f", "Welcome to KWIQ", "Accept", "Cancel"],
    ],
)
def test_complete_last_body_with_proven_footer_and_page_tail_resolves_match(tail):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First complete body")
        + heading("Feb 1, 2023")
        + activity("Second complete body")
        + footer()
    )

    assert (
        match_timeline_html_event(facts, raw_note("Second complete body", *tail))
        == facts.activities[1]
    )


def test_footer_suffix_requires_actual_footer_proof_and_the_last_activity():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    html = (
        heading("Mar 6, 2023")
        + activity("First complete body")
        + heading("Feb 1, 2023")
        + activity("Second complete body")
    )

    assert (
        match_timeline_html_event(
            parse_timeline_html(html),
            raw_note("Second complete body", "End of Timeline"),
        )
        is None
    )
    assert (
        match_timeline_html_event(
            parse_timeline_html(html + footer()),
            raw_note("First complete body", "End of Timeline"),
        )
        is None
    )
    assert (
        match_timeline_html_event(
            parse_timeline_html(html + footer()),
            raw_note("Second complete body", "End of TimelineX"),
        )
        is None
    )


def test_date_literal_inside_the_matching_note_is_preserved_as_activity_content():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Closing appointment<p>Sep 4, 2025</p>")
        + heading("Feb 1, 2023")
        + activity("Another appointment")
    )
    lines = raw_note("Closing appointment", "SEP 4, 2025")
    original = list(lines)

    match = match_timeline_html_event(facts, lines)

    assert match == facts.activities[0]
    assert match.day == date(2023, 3, 6)
    assert match.text.endswith("Closing appointment Sep 4, 2025")
    assert lines == original


def test_date_literal_and_actual_heading_can_leave_multiple_complete_candidates():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Closing appointment")
        + heading("Sep 4, 2025")
        + activity("Closing appointment<p>Sep 4, 2025</p>")
    )

    assert (
        match_timeline_html_event(facts, raw_note("Closing appointment", "SEP 4, 2025"))
        is None
    )


def grouped_tail_lines() -> list[str]:
    return raw_note("First activity", "FEB 1, 2023") + [
        "NEIGHBORHOODS",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "Second activity",
        "End of Timeline",
        "Welcome to KWIQ",
        "Accept",
    ]


def grouped_tail_html() -> str:
    return (
        heading("Mar 6, 2023")
        + activity("First activity")
        + heading("Feb 1, 2023")
        + activity("Second activity", kind="neighborhoods")
        + footer()
    )


def test_complete_structural_tail_removes_only_footer_and_preserves_exact_raw_lines():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_tail_lines,
    )

    facts = parse_timeline_html(grouped_tail_html())
    lines = grouped_tail_lines()
    lines[4] = "First   activity"
    original = list(lines)

    clean = verified_timeline_tail_lines(facts, facts.activities[0], lines)

    assert clean == original[:11]
    assert clean[4] == "First   activity"
    assert "FEB 1, 2023" in clean
    assert "NEIGHBORHOODS" in clean
    assert lines == original


def test_tail_cleanup_preserves_date_literals_and_footer_words_inside_real_activity():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_tail_lines,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Training<p>End of Timeline</p><p>Sep 4, 2025</p>")
        + activity("Second activity", kind="neighborhoods")
        + footer()
    )
    lines = raw_note("Training", "End of Timeline", "SEP 4, 2025") + [
        "NEIGHBORHOODS",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "Second activity",
        "End of Timeline",
        "Welcome to KWIQ",
    ]

    clean = verified_timeline_tail_lines(facts, facts.activities[0], lines)

    assert clean == lines[:-2]
    assert clean.count("End of Timeline") == 1
    assert "SEP 4, 2025" in clean


def test_tail_cleanup_can_include_a_real_later_activity_without_by_author_metadata():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_tail_lines,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First activity")
        + '<div data-test="timeline-source-change"><div>Source</div><div>7:15 PM</div>'
        + "<div>Updated</div><div>Updated source details</div></div>"
        + footer()
    )
    lines = raw_note("First activity") + [
        "Source",
        "7:15 PM",
        "Updated",
        "Updated source details",
        "End of Timeline",
    ]

    assert verified_timeline_tail_lines(facts, facts.activities[0], lines) == lines[:-1]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw[:10] + ["Different body"] + raw[11:],
        lambda raw: raw[:5] + ["JAN 1, 2000"] + raw[6:],
        lambda raw: raw[:5] + raw[6:],
        lambda raw: raw[:11] + ["Unproven added content"] + raw[11:],
        lambda raw: raw[:5] + raw[11:],
        lambda raw: raw[:11],
    ],
)
def test_incomplete_or_edited_structural_tail_cannot_authorize_footer_cleanup(mutation):
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_tail_lines,
    )

    facts = parse_timeline_html(grouped_tail_html())
    lines = mutation(grouped_tail_lines())

    assert verified_timeline_tail_lines(facts, facts.activities[0], lines) is None


def test_tail_cleanup_requires_terminal_footer_proof_and_owned_activity():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_tail_lines,
    )

    facts = parse_timeline_html(grouped_tail_html().removesuffix(footer()))
    assert (
        verified_timeline_tail_lines(facts, facts.activities[0], grouped_tail_lines())
        is None
    )
    facts = parse_timeline_html(grouped_tail_html())
    other = parse_timeline_html(activity("An unrelated activity")).activities[0]
    assert verified_timeline_tail_lines(facts, other, grouped_tail_lines()) is None


def navigation_lines(*tail: str) -> list[str]:
    return [
        "SmartPlans",
        "0",
        "Tasks",
        "Notes",
        "Saved Searches",
        "All Time",
        "All Activity",
        "AI Summary",
        "A summary may appear here.",
        "MAR 6, 2023",
        *tail,
    ]


def test_navigation_recovery_keeps_the_complete_sequence_and_exact_original_lines():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(grouped_tail_html())
    tail = grouped_tail_lines()
    tail[4] = "First   activity"
    lines = navigation_lines(*tail)
    original = list(lines)

    recovered = recover_timeline_navigation_tail(facts, lines)

    assert recovered is not None
    assert recovered.first_activity_index == 0
    assert recovered.activity_count == 2
    assert recovered.lines == tuple(tail[:11])
    assert lines == original


def test_navigation_recovery_resolves_repeated_complete_activities_by_entire_sequence():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Repeated body")
        + activity("Repeated body")
        + heading("Feb 1, 2023")
        + activity("Final body")
        + footer()
    )
    tail = (
        raw_note("Repeated body")
        + raw_note("Repeated body", "FEB 1, 2023")
        + raw_note("Final body")
    )

    recovered = recover_timeline_navigation_tail(
        facts, navigation_lines(*tail, "End of Timeline")
    )

    assert recovered is not None
    assert recovered.first_activity_index == 0
    assert recovered.activity_count == 3
    assert recovered.lines == tuple(tail)


def test_navigation_recovery_accepts_exact_eof_and_preserves_body_literals():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Earlier body")
        + heading("Feb 1, 2023")
        + activity("Training<p>End of Timeline</p><p>Sep 4, 2025</p>")
    )
    tail = raw_note("Training", "End of Timeline", "SEP 4, 2025")

    recovered = recover_timeline_navigation_tail(facts, navigation_lines(*tail))

    assert recovered is not None
    assert recovered.first_activity_index == 1
    assert recovered.activity_count == 1
    assert recovered.lines == tuple(tail)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda lines: lines[:4] + ["Different first body"] + lines[5:],
        lambda lines: lines[:5] + ["JAN 1, 2000"] + lines[6:],
        lambda lines: lines[:10] + ["Different final body"] + lines[11:],
        lambda lines: lines[:5] + lines[11:],
        lambda lines: lines[:11] + ["Unproven extra text"] + lines[11:],
    ],
)
def test_navigation_recovery_rejects_changed_or_incomplete_sequences_without_skipping_ahead(
    mutation,
):
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(grouped_tail_html())

    assert (
        recover_timeline_navigation_tail(
            facts, navigation_lines(*mutation(grouped_tail_lines()))
        )
        is None
    )


def test_navigation_recovery_requires_navigation_context_and_proven_footer_or_exact_eof():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(grouped_tail_html().removesuffix(footer()))

    assert (
        recover_timeline_navigation_tail(facts, navigation_lines(*grouped_tail_lines()))
        is None
    )
    assert recover_timeline_navigation_tail(facts, grouped_tail_lines()[:11]) is None


def test_navigation_recovery_handles_an_activity_without_by_author_metadata():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + '<div data-test="timeline-source-change"><div>Source</div><div>7:15 PM</div>'
        + "<div>Updated</div><div>Updated source details</div></div>"
        + footer()
    )
    tail = ["SOURCE", "7:15 PM", "Updated", "Updated source details"]

    recovered = recover_timeline_navigation_tail(
        facts, navigation_lines(*tail, "End of Timeline")
    )

    assert recovered is not None
    assert recovered.activity_count == 1
    assert recovered.lines == tuple(tail)


def test_navigation_recovery_accepts_a_complete_leading_span_with_proven_next_heading():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("First neighborhood", kind="neighborhoods")
        + activity("Second neighborhood", kind="neighborhoods")
        + heading("Feb 1, 2023")
        + activity("Separately captured email", kind="email")
        + footer()
    )
    tail = [
        "NEIGHBORHOODS",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "First neighborhood",
        "NEIGHBORHOODS",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "Second neighborhood",
    ]

    recovered = recover_timeline_navigation_tail(
        facts, navigation_lines(*tail, "FEB 1, 2023")
    )

    assert recovered is not None
    assert recovered.first_activity_index == 0
    assert recovered.activity_count == 2
    assert recovered.lines == tuple(tail)


def test_navigation_partial_span_cannot_guess_a_missing_or_wrong_next_boundary():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(grouped_tail_html())

    assert (
        recover_timeline_navigation_tail(
            facts, navigation_lines(*raw_note("First activity"))
        )
        is None
    )
    assert (
        recover_timeline_navigation_tail(
            facts, navigation_lines(*raw_note("First activity", "JAN 1, 2000"))
        )
        is None
    )


def test_navigation_span_requires_one_complete_interpretation_not_a_literal_date_guess():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        recover_timeline_navigation_tail,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Same body")
        + heading("Feb 1, 2023")
        + activity("Same body<p>Feb 1, 2023</p>")
    )

    assert (
        recover_timeline_navigation_tail(
            facts, navigation_lines(*raw_note("Same body", "FEB 1, 2023"))
        )
        is None
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Message<div><button><span>Reply</span></button></div>", True),
        ("Message<div>Reply</div>", False),
        ("Message<span>Reply</span>", False),
        ("Message<button>Reply</button><div>Actual ending</div>", False),
        ("Message<button hidden>Reply</button>", False),
        ("Message<button>Reply to sender</button>", False),
    ],
)
def test_only_a_visible_trailing_reply_button_is_control_evidence(body, expected):
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(activity(body, kind="text"))

    assert facts.activities[0].trailing_reply_button is expected


def test_quoted_unique_header_with_conflicting_body_does_not_steal_a_later_date():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Earlier note quotes a later header", time="8:15 AM")
        + heading("Feb 1, 2023")
        + activity("The real later note")
    )

    assert (
        match_timeline_html_event(facts, raw_note("Different quoted content")) is None
    )
    assert (
        match_timeline_html_event(facts, raw_note("The real later note"))
        == facts.activities[1]
    )


@pytest.mark.parametrize(
    ("raw_body", "expected_match"),
    [
        ("Complete", True),
        ("Complete body", True),
        ("Complete body with capture tail", True),
        ("Complet", False),
    ],
)
def test_unique_header_requires_compatible_nonempty_body_at_word_boundaries(
    raw_body, expected_match
):
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        parse_timeline_html,
    )

    facts = parse_timeline_html(activity("Complete body"))

    assert (
        match_timeline_html_event(facts, raw_note(raw_body)) is not None
    ) is expected_match


def fragment_facts_and_raw():
    from services.command_contact_timeline_html import parse_timeline_html

    facts = parse_timeline_html(
        heading("Mar 6, 2023")
        + activity("Call<div>Actual business body</div>")
        + heading("Feb 1, 2023")
        + activity("Other real activity", kind="neighborhoods")
        + footer()
    )
    raw = [
        "Call",
        "Actual business body",
        "FEB 1, 2023",
        "NEIGHBORHOODS",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "Other real activity",
        "End of Timeline",
        "Welcome to KWIQ",
    ]
    return facts, raw


def test_fragment_cleanup_preserves_full_source_tail_without_inventing_event_identity():
    from services.command_contact_timeline_html import (
        match_timeline_html_event,
        verified_timeline_fragment_tail_lines,
    )

    facts, raw = fragment_facts_and_raw()
    original = list(raw)

    assert match_timeline_html_event(facts, raw) is None
    assert verified_timeline_fragment_tail_lines(facts, raw) == original[:-2]
    assert raw == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: ["Cal", *raw[1:]],
        lambda raw: [raw[0], "Different body", *raw[2:]],
        lambda raw: [*raw[:2], "JAN 1, 2000", *raw[3:]],
        lambda raw: [*raw[:7], "Different following activity", *raw[8:]],
        lambda raw: [*raw[:2], *raw[8:]],
        lambda raw: raw[:8],
    ],
)
def test_fragment_cleanup_rejects_partial_edited_or_unbounded_suffixes(mutation):
    from services.command_contact_timeline_html import (
        verified_timeline_fragment_tail_lines,
    )

    facts, raw = fragment_facts_and_raw()

    assert verified_timeline_fragment_tail_lines(facts, mutation(raw)) is None


def test_fragment_cleanup_never_treats_real_footer_words_as_external_controls():
    from services.command_contact_timeline_html import (
        parse_timeline_html,
        verified_timeline_fragment_tail_lines,
    )

    facts = parse_timeline_html(
        activity("Call<div>End of Timeline</div><div>Keep this sentence.</div>")
        + footer()
    )
    raw = [
        "Call",
        "End of Timeline",
        "Keep this sentence.",
        "End of Timeline",
        "Welcome to KWIQ",
    ]

    assert verified_timeline_fragment_tail_lines(facts, raw) == raw[:-2]
