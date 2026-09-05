"""Role-preserving timeline recovery from synthetic accessibility snapshots."""

from datetime import date

import pytest

from services.command_contact_timeline_html import match_timeline_html_event

CONTEXT = (
    "- generic: AI Summary\n"
    "- button\n"
    "- generic: A summary will be provided after more activities.\n"
    '- link "Learn More":\n'
    "  - /url: https://example.test/help\n"
)


def heading(value: str, *, level: int = 5) -> str:
    return f'- heading "{value}" [level={level}]\n'


def note(body: str, *, time: str = "2:16 PM") -> str:
    return (
        f"- generic: Note\n- generic: {time}\n- generic: Created\n"
        "- generic: By Example Agent\n- separator\n"
        f"{body}\n"
    )


def test_snapshot_roles_separate_profile_dates_note_dates_and_terminal_footer():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    snapshot = (
        "- generic: Birthday\n- paragraph: Jan 1, 1980\n"
        + heading("Apr 29, 2022")
        + CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Open house\n- generic: Follow up next week.")
        + heading("Feb 1, 2025")
        + note("- generic: Closing appointment\n- generic: Sep 4, 2025")
        + "- paragraph: End of Timeline\n"
        + CONSENT_PANEL
    )

    facts = parse_timeline_snapshot(snapshot)

    assert [(item.day, item.before_event_index) for item in facts.headings] == [
        (date(2025, 4, 28), 0),
        (date(2025, 2, 1), 1),
    ]
    assert [item.day for item in facts.activities] == [
        date(2025, 4, 28),
        date(2025, 2, 1),
    ]
    assert [item.index for item in facts.activities] == [0, 1]
    assert facts.activities[0].header == (
        "Note",
        "2:16 PM",
        "Created",
        "By Example Agent",
    )
    assert facts.activities[1].text.endswith("Closing appointment Sep 4, 2025")
    assert "Welcome to KWIQ" not in facts.activities[1].text
    assert facts.terminal_footer is True
    assert (
        match_timeline_html_event(
            facts,
            [
                "NOTE",
                "2:16 PM",
                "Created",
                "By Example Agent",
                "Open house",
                "Follow up next week.",
                "FEB 1, 2025",
            ],
        )
        == facts.activities[0]
    )


def test_generic_footer_words_and_plain_date_values_remain_actual_body_text():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- generic: Training\n- generic: End of Timeline\n- generic: Sep 4, 2025"
        )
    )

    assert facts.activities[0].text.endswith("Training End of Timeline Sep 4, 2025")
    assert facts.activities[0].day == date(2025, 4, 28)
    assert facts.terminal_footer is False


def test_same_day_activities_are_separated_only_by_four_valid_generic_header_fields():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: A note\n- generic: Call\n- generic: Discuss this later.")
        + note("- generic: Another note", time="3:16 PM")
    )

    assert len(facts.activities) == 2
    assert facts.activities[0].text.endswith("A note Call Discuss this later.")
    assert [item.heading_index for item in facts.activities] == [0, 0]


@pytest.mark.parametrize(
    "snapshot",
    [
        heading("Apr 28, 2025") + note("- generic: Missing summary context"),
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Invalid time", time="25:61 PM"),
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Wrong author role").replace(
            "- generic: By", "- paragraph: By"
        ),
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Missing author").replace(
            "- generic: By Example Agent\n", ""
        ),
        "AI Summary\nApr 28, 2025\nNote\n2:16 PM\nCreated\nBy Example Agent\nA note",
    ],
)
def test_missing_context_or_unproven_header_never_creates_an_activity(snapshot):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    assert parse_timeline_snapshot(snapshot).activities == ()


def test_snapshot_body_values_align_with_legacy_quoted_link_and_button_labels():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    body_lines = [
        '- generic: "Open house"',
        '- paragraph: "From: example@example.test"',
        '- link "Property details":',
        "  - /url: https://example.test/property",
        "- text: Requested another appointment.",
        "- strong: Tomorrow",
        '- button "Reply": Reply',
    ]
    facts = parse_timeline_snapshot(
        CONTEXT + heading("Apr 28, 2025") + note("\n".join(body_lines))
    )
    legacy_body = (
        "Open house From: example@example.test Property details "
        "Requested another appointment. Tomorrow Reply"
    )

    assert facts.activities[0].text.endswith(legacy_body)
    assert "https://example.test/property" not in facts.activities[0].text


def test_footer_paragraph_before_another_activity_is_content_not_a_terminal_footer():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First note\n- paragraph: End of Timeline")
        + note("- generic: Second note", time="3:16 PM")
    )

    assert len(facts.activities) == 2
    assert facts.activities[0].text.endswith("First note End of Timeline")
    assert facts.terminal_footer is False


def test_footer_paragraph_before_a_later_date_heading_is_not_terminal():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First note\n- paragraph: End of Timeline")
        + heading("Feb 1, 2025")
        + note("- generic: Second note")
    )

    assert len(facts.headings) == len(facts.activities) == 2
    assert facts.activities[0].text.endswith("First note End of Timeline")
    assert facts.activities[1].day == date(2025, 2, 1)
    assert facts.terminal_footer is False


def test_nested_roles_cannot_split_the_activity_or_supply_a_footer_or_day():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    nested = "\n".join(
        "  " + line
        for line in (
            heading("Jan 1, 2000") + note("- paragraph: End of Timeline")
        ).splitlines()
    )
    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Quoted activity\n" + nested)
        + "- paragraph: End of Timeline\n"
    )

    assert len(facts.activities) == len(facts.headings) == 1
    assert facts.activities[0].day == date(2025, 4, 28)
    assert "Quoted activity Jan 1, 2000 Note 2:16 PM" in facts.activities[0].text
    assert facts.activities[0].text.endswith("End of Timeline")
    assert facts.terminal_footer is True


def test_only_level_five_dates_apply_and_invalid_day_resets_prior_day():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Jan 1, 2000", level=4)
        + note("- generic: Date unknown")
        + heading("Apr 28, 2025")
        + note("- generic: Date known")
        + heading("Feb 30, 2025")
        + note("- generic: Invalid day")
    )

    assert [item.day for item in facts.activities] == [None, date(2025, 4, 28), None]


def test_nested_false_summary_context_does_not_hide_a_later_real_timeline():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        "- generic: Profile description\n  - generic: AI Summary\n"
        + CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: A real note")
    )

    assert len(facts.activities) == 1
    assert facts.activities[0].day == date(2025, 4, 28)


@pytest.mark.parametrize(
    "kind", ["Call", "Email", "Text", "SmartPlans", "System", "Contact", "Source"]
)
def test_other_known_generic_activity_headers_keep_capture_order(kind):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First").replace("- generic: Note\n", f"- generic: {kind}\n")
        + note("- generic: Second")
    )

    assert [item.header[0] for item in facts.activities] == [kind, "Note"]
    assert [item.index for item in facts.activities] == [0, 1]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('- generic: Message\n- button "Reply"', True),
        ('- generic: Message\n- button "Reply": Reply\n- separator', True),
        ("- generic: Message\n- generic: Reply", False),
        ("- generic: Message\n- paragraph: Reply", False),
        ('- generic: Message\n- button "Reply"\n- generic: Actual ending', False),
    ],
)
def test_snapshot_reply_control_requires_the_actual_last_visible_button_role(
    body, expected
):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(CONTEXT + heading("Apr 28, 2025") + note(body))

    assert facts.activities[0].trailing_reply_button is expected


@pytest.mark.parametrize(
    "kind",
    [
        "Source",
        "Property Inquiry",
        "Listing",
        "Collection",
        "Saved Search",
        "AGENT SITE",
        "Client Inquiry",
        "In Person Tour",
        "Home Valuation Request",
        "Google Calendar Invite",
        "INFO",
    ],
)
def test_observed_automated_kinds_accept_three_generic_metadata_fields_and_separator(
    kind,
):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + f"- generic: {kind}\n- generic: 2:16 PM\n- generic: Updated\n"
        + "- separator\n- generic: Automated event body\n- paragraph: End of Timeline\n"
    )

    assert len(facts.activities) == 1
    assert facts.activities[0].header == (kind, "2:16 PM", "Updated")
    assert facts.activities[0].day == date(2025, 4, 28)
    assert facts.activities[0].text.endswith("Automated event body")
    assert facts.terminal_footer is True


@pytest.mark.parametrize("kind", ["Note", "Email", "Text", "Call"])
def test_human_activity_kinds_still_require_a_by_author_field(kind):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + f"- generic: {kind}\n- generic: 2:16 PM\n- generic: Updated\n"
        + "- separator\n- generic: This has no author\n- paragraph: End of Timeline\n"
    )

    assert facts.activities == ()


def test_nested_automated_metadata_cannot_split_a_human_note():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- generic: Quoted example\n  - generic: Source\n  - generic: 2:16 PM\n"
            "  - generic: Added\n  - separator\n  - generic: Quoted source body"
        )
        + "- paragraph: End of Timeline\n"
    )

    assert len(facts.activities) == 1
    assert facts.activities[0].text.endswith(
        "Quoted example Source 2:16 PM Added Quoted source body"
    )


@pytest.mark.parametrize(
    "tail",
    [
        "- generic: Unproven direct body",
        "- separator",
        "- paragraph: Added\n- separator\n- generic: Body",
    ],
)
def test_automated_header_requires_complete_generic_metadata_and_body_boundary(tail):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    prefix = "- generic: Source\n- generic: 2:16 PM\n"
    if not tail.startswith("- paragraph: Added"):
        prefix += "- generic: Added\n"

    assert (
        parse_timeline_snapshot(
            CONTEXT + heading("Apr 28, 2025") + prefix + tail
        ).activities
        == ()
    )


def test_empty_automated_body_is_complete_at_an_actual_next_heading():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + "- generic: AGENT SITE\n- generic: 2:16 PM\n- generic: Visited\n"
        + heading("Feb 1, 2025")
        + note("- generic: Later activity")
        + "- paragraph: End of Timeline\n"
    )

    assert len(facts.activities) == 2
    assert facts.activities[0].text == "AGENT SITE 2:16 PM Visited"
    assert facts.activities[1].day == date(2025, 2, 1)


@pytest.mark.parametrize("kind", ["Property Inquiry", "Google Calendar Invite"])
def test_observed_two_field_automated_headers_require_a_real_separator_and_body(kind):
    from services.command_contact_timeline_html import recover_timeline_navigation_tail
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    snapshot = (
        CONTEXT
        + heading("Apr 28, 2025")
        + f"- generic: {kind}\n- generic: 2:16 PM\n"
        + "- separator\n- generic: Automated body\n- paragraph: End of Timeline\n"
    )
    facts = parse_timeline_snapshot(snapshot)

    assert facts.activities[0].header == (kind, "2:16 PM")
    assert facts.activities[0].text == f"{kind} 2:16 PM Automated body"
    raw = navigation_lines(kind, "2:16 PM", "Automated body", "End of Timeline")
    assert recover_timeline_navigation_tail(facts, raw).activity_count == 1
    assert (
        parse_timeline_snapshot(snapshot.replace("- separator\n", "")).activities == ()
    )


def test_nested_two_field_automated_header_remains_quoted_human_note_content():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- generic: Example\n  - generic: Property Inquiry\n  - generic: 2:16 PM\n"
            "  - separator\n  - generic: This is quoted"
        )
        + "- paragraph: End of Timeline\n"
    )

    assert len(facts.activities) == 1
    assert facts.activities[0].text.endswith(
        "Example Property Inquiry 2:16 PM This is quoted"
    )


def test_canonical_lines_preserve_quoted_generic_values_with_exact_legacy_projection():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note('- generic: Contact updated\n- generic: Status changed to "Assigned"')
        + "- paragraph: End of Timeline\n"
    )

    event = facts.activities[0]
    assert event.canonical_lines == (
        "Note",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Contact updated",
        'Status changed to "Assigned"',
    )
    assert event.legacy_text == "Note 2:16 PM Created By Example Agent Contact updated"
    assert event.text.endswith('Status changed to "Assigned"')


def test_archive_backed_group_restores_only_proven_quoted_generic_omissions():
    from services.command_contact_timeline_html import (
        recover_timeline_navigation_archive_tail,
        recover_timeline_navigation_tail,
    )
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First body")
        + heading("Feb 1, 2025")
        + note(
            '- generic: Contact updated\n- generic: Status changed to "Assigned"',
            time="3:16 PM",
        )
        + "- paragraph: End of Timeline\n"
    )
    tail = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "First body",
        "FEB 1, 2025",
        "NOTE",
        "3:16 PM",
        "Created",
        "By Example Agent",
        "Contact updated",
        "End of Timeline",
        "Welcome to KWIQ",
    ]
    raw = navigation_lines(*tail)
    original = list(raw)

    assert recover_timeline_navigation_tail(facts, raw) is None
    recovered = recover_timeline_navigation_archive_tail(facts, raw)

    assert recovered is not None
    assert recovered.archive_restored is True
    assert recovered.first_activity_index == 0
    assert recovered.activity_count == 2
    assert recovered.lines == (
        *facts.activities[0].canonical_lines,
        "Feb 1, 2025",
        *facts.activities[1].canonical_lines,
    )
    assert raw == original


@pytest.mark.parametrize("role", ["text", "paragraph", "strong"])
def test_archive_restoration_never_omits_quoted_values_from_unapproved_roles(role):
    from services.command_contact_timeline_html import (
        recover_timeline_navigation_archive_tail,
    )
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(f'- {role}: Status changed to "Assigned"')
        + "- paragraph: End of Timeline\n"
    )
    raw = navigation_lines(
        "NOTE", "2:16 PM", "Created", "By Example Agent", "End of Timeline"
    )

    assert recover_timeline_navigation_archive_tail(facts, raw) is None


def test_archive_restoration_rejects_edits_and_missing_unquoted_body():
    from services.command_contact_timeline_html import (
        recover_timeline_navigation_archive_tail,
    )
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note('- generic: Retained body\n- generic: Status changed to "Assigned"')
        + "- paragraph: End of Timeline\n"
    )
    for body in ([], ["Edited body"]):
        raw = navigation_lines(
            "NOTE", "2:16 PM", "Created", "By Example Agent", *body, "End of Timeline"
        )
        assert recover_timeline_navigation_archive_tail(facts, raw) is None


def test_flat_snapshot_eof_cannot_authorize_grouping_sitewide_controls_as_activity():
    from services.command_contact_timeline_html import (
        recover_timeline_navigation_archive_tail,
        recover_timeline_navigation_tail,
    )
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    raw_tail = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Actual body",
        "Welcome to KWIQ",
        "Accept",
    ]
    snapshot = (
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Actual body")
        + '- generic: Welcome to KWIQ\n- button "Accept"\n'
    )
    facts = parse_timeline_snapshot(snapshot)

    assert recover_timeline_navigation_tail(facts, navigation_lines(*raw_tail)) is None
    with_omission = parse_timeline_snapshot(
        snapshot.replace(
            "- generic: Actual body",
            '- generic: Actual body\n- generic: Changed to "Assigned"',
        )
    )
    assert (
        recover_timeline_navigation_archive_tail(
            with_omission, navigation_lines(*raw_tail)
        )
        is None
    )


CONSENT_PANEL = (
    "- generic: \ue90f\n- generic: Welcome to KWIQ\n- button\n"
    "- text: KWIQ uses artificial intelligence (AI) to provide assistance.\n"
    "- text: By accepting, you agree to the\n"
    '- link "Terms of Use":\n  - /url: https://legal.kw.com/termsofuse\n'
    "- text: and\n"
    '- link "Privacy Policy":\n  - /url: https://headquarters.kw.com/privacy-policy/\n'
    "- text: .\n- checkbox\n"
    '- button "Accept":\n  - generic: Accept\n'
    '- button "Cancel":\n  - generic: Cancel\n'
)


def test_complete_role_proven_consent_panel_bounds_capture_without_inventing_a_footer():
    from services.command_contact_timeline_html import recover_timeline_navigation_tail
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + "- generic: AGENT SITE\n- generic: 2:16 PM\n- generic: Registered\n- separator\n"
        + CONSENT_PANEL
    )
    raw = navigation_lines(
        "AGENT SITE",
        "2:16 PM",
        "Registered",
        "\ue90f",
        "Welcome to KWIQ",
        "Accept",
        "Cancel",
    )

    assert facts.activities[0].text == "AGENT SITE 2:16 PM Registered"
    assert facts.terminal_footer is False
    assert facts.complete_eof is False
    assert facts.terminal_boundary == ("\ue90f", "Welcome to KWIQ")
    recovered = recover_timeline_navigation_tail(facts, raw)
    assert recovered is not None
    assert recovered.lines == ("AGENT SITE", "2:16 PM", "Registered")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.replace("- checkbox\n", "- generic: checkbox\n"),
        lambda value: value.replace('- button "Accept":', "- generic: Accept"),
        lambda value: value.replace(
            '- link "Terms of Use":', "- generic: Terms of Use"
        ),
        lambda value: value.replace("\ue90f", "x"),
        lambda value: value.replace(
            "KWIQ uses artificial intelligence (AI)", "A quoted example"
        ),
        lambda value: value.split('- button "Cancel"')[0],
        lambda value: "\n".join("  " + line for line in value.splitlines()),
    ],
)
def test_incomplete_generic_or_nested_consent_words_are_not_a_structural_boundary(
    mutation,
):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Actual body")
        + mutation(CONSENT_PANEL)
    )

    assert facts.terminal_boundary == ()
    assert "Welcome to KWIQ" in facts.activities[0].text


def test_consent_panel_cannot_end_the_capture_before_later_activity_headers():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First body")
        + CONSENT_PANEL
        + heading("Feb 1, 2025")
        + note("- generic: Later activity")
    )

    assert facts.terminal_boundary == ()
    assert len(facts.activities) == 2
    assert "Welcome to KWIQ" in facts.activities[0].text


def test_consent_boundary_cleanup_preserves_real_date_and_footer_literals_and_rejects_edits():
    from services.command_contact_timeline_html import recover_timeline_navigation_tail
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- generic: Training\n- generic: End of Timeline\n- generic: Sep 4, 2025"
        )
        + CONSENT_PANEL
    )
    tail = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Training",
        "End of Timeline",
        "SEP 4, 2025",
    ]
    raw = navigation_lines(*tail, "\ue90f", "Welcome to KWIQ", "Accept", "Cancel")

    assert recover_timeline_navigation_tail(facts, raw).lines == tuple(tail)
    raw[-6] = "Different body"
    assert recover_timeline_navigation_tail(facts, raw) is None


def test_only_the_final_footer_paragraph_ends_a_note_and_prior_literal_is_preserved():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- paragraph: End of Timeline\n- generic: Preserve the next sentence.")
        + "- paragraph: End of Timeline\n"
        + CONSENT_PANEL
    )

    assert facts.terminal_footer is True
    assert facts.activities[0].text.endswith(
        "End of Timeline Preserve the next sentence."
    )
    assert facts.activities[0].canonical_lines[-2:] == (
        "End of Timeline",
        "Preserve the next sentence.",
    )


@pytest.mark.parametrize("after_body", ["", CONSENT_PANEL])
def test_single_literal_footer_paragraph_cannot_discard_following_note_text(after_body):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- paragraph: End of Timeline\n- generic: Preserve the next sentence.")
        + after_body
    )

    assert facts.terminal_footer is False
    assert facts.activities[0].text.endswith(
        "End of Timeline Preserve the next sentence."
    )
    assert bool(facts.terminal_boundary) is bool(after_body)


def test_welcome_words_without_real_consent_controls_cannot_discard_business_text():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- paragraph: End of Timeline\n- generic: Welcome to KWIQ\n- generic: Preserve this business sentence."
        )
    )

    assert facts.terminal_footer is False
    assert facts.activities[0].text.endswith(
        "End of Timeline Welcome to KWIQ Preserve this business sentence."
    )


def test_fragment_tail_cleanup_can_use_only_the_approved_legacy_line_projection():
    from services.command_contact_timeline_html import (
        verified_timeline_fragment_tail_lines,
    )
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            '- generic: Call\n- generic: Changed to "Assigned"\n- generic: Remaining business body'
        )
        + "- paragraph: End of Timeline\n"
    )
    raw = ["Call", "Remaining business body", "End of Timeline"]

    assert verified_timeline_fragment_tail_lines(facts, raw) == raw[:-1]
    assert facts.activities[0].legacy_lines == (
        "Note",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Call",
        "Remaining business body",
    )


NOTIFICATIONS_PANEL = (
    "- generic: \ue90f\n"
    '- heading "Notifications" [level=2]\n'
    '- link "\ue95f":\n  - /url: "#"\n  - generic: \ue95f\n'
    "- generic: \ue91b\n- generic: Unread\n- generic: Read\n"
    "- generic: 0 Unread\n- text: All Notifications\n"
    "- generic: \ue98c\n- generic: \ue914\n"
    "- generic: You don’t have any unread notifications.\n"
    "- generic: Mark All as Read\n"
    '- heading "Help & Information" [level=3]\n'
    "- generic: \ue91b\n- button\n"
)


def test_complete_notifications_panel_proves_footer_after_all_activity_content():
    from services.command_contact_timeline_html import verified_timeline_tail_lines
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: First actual body")
        + "- generic: Property Inquiry\n- generic: 1:16 PM\n"
        + "- generic: Registered\n- separator\n"
        + '- link "Property details":\n  - /url: https://example.test/property\n'
        + "- paragraph: End of Timeline\n"
        + NOTIFICATIONS_PANEL
    )
    raw = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "First actual body",
        "Property Inquiry",
        "1:16 PM",
        "Registered",
        "Property details",
        "End of Timeline",
        "\ue90f",
    ]

    assert facts.terminal_footer is True
    assert facts.terminal_boundary == ()
    assert len(facts.activities) == 2
    assert facts.activities[-1].text.endswith("Registered Property details")
    assert verified_timeline_tail_lines(facts, facts.activities[0], raw) == raw[:-2]


def test_notifications_footer_restores_complete_bodyless_automated_navigation_group():
    from services.command_contact_timeline_html import recover_timeline_navigation_tail
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot
    from tests.test_command_contact_timeline_html import navigation_lines

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + "- generic: AGENT SITE\n- generic: 2:16 PM\n"
        + "- generic: Registered\n- separator\n- paragraph: End of Timeline\n"
        + NOTIFICATIONS_PANEL
    )
    raw = navigation_lines(
        "AGENT SITE", "2:16 PM", "Registered", "End of Timeline", "\ue90f"
    )

    group = recover_timeline_navigation_tail(facts, raw)
    assert group is not None
    assert group.activity_count == 1
    assert group.lines == ("AGENT SITE", "2:16 PM", "Registered")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda panel: panel.replace(
            '- heading "Notifications" [level=2]', "- generic: Notifications"
        ),
        lambda panel: panel.replace("[level=2]", "[level=3]"),
        lambda panel: panel.replace('- link "\ue95f":', "- generic: \ue95f"),
        lambda panel: panel.replace("  - generic: \ue95f\n", ""),
        lambda panel: panel.replace("- generic: Unread", "- text: Unread"),
        lambda panel: panel.replace(
            "- text: All Notifications", "- generic: All Notifications"
        ),
        lambda panel: panel.replace("Mark All as Read", "A business reminder"),
        lambda panel: panel.replace("- generic: \ue90f", "- generic: x"),
        lambda panel: panel.replace(
            "- generic: Unread",
            "  - generic: Keep this nested business sentence.\n- generic: Unread",
        ),
        lambda panel: panel.replace("- button\n", ""),
        lambda panel: "\n".join("  " + line for line in panel.splitlines()),
        lambda panel: (
            panel + heading("Feb 1, 2025") + note("- generic: Later actual activity")
        ),
        lambda panel: panel + "- generic: Future Activity Kind\n- generic: 1:16 PM\n",
    ],
)
def test_notifications_labels_with_incomplete_nested_or_different_roles_do_not_prove_footer(
    mutation,
):
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Actual body\n- paragraph: End of Timeline")
        + mutation(NOTIFICATIONS_PANEL)
    )

    assert facts.terminal_footer is False
    assert facts.terminal_boundary == ()
    assert "Actual body End of Timeline" in facts.activities[0].text
    assert "Notifications" in facts.activities[0].text


def test_notifications_panel_without_actual_footer_does_not_create_a_new_boundary():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note("- generic: Actual body")
        + NOTIFICATIONS_PANEL
    )

    assert facts.terminal_footer is False
    assert facts.terminal_boundary == ()
    assert "Notifications" in facts.activities[0].text


def test_notifications_footer_proof_keeps_earlier_literal_paragraph_and_business_sentence():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- paragraph: End of Timeline\n- generic: Preserve this business sentence."
        )
        + "- paragraph: End of Timeline\n"
        + NOTIFICATIONS_PANEL
    )

    assert facts.terminal_footer is True
    assert facts.activities[0].canonical_lines[-2:] == (
        "End of Timeline",
        "Preserve this business sentence.",
    )


def test_notifications_panel_cannot_skip_nested_business_text_after_literal_footer():
    from services.command_contact_timeline_snapshot import parse_timeline_snapshot

    facts = parse_timeline_snapshot(
        CONTEXT
        + heading("Apr 28, 2025")
        + note(
            "- paragraph: End of Timeline\n  - generic: Preserve this nested sentence."
        )
        + NOTIFICATIONS_PANEL
    )

    assert facts.terminal_footer is False
    assert "End of Timeline Preserve this nested sentence." in facts.activities[0].text
