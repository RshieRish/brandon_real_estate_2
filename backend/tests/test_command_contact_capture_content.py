"""Synthetic source-precision regressions; never contain customer data."""

from datetime import date

import pytest

from services.command_contact_capture_content import (
    read_mailing_address,
    read_timeline_capture,
)


def profile(address):
    return [
        "Email",
        "--",
        "Phone",
        "--",
        "Home Address",
        "--",
        "Mailing Address",
        *address,
        "Legal Name",
        "Example Person",
        "Social Profiles",
        "--",
        "About",
        "Description",
        "--",
        "Timeline",
        "Opportunities",
    ]


def test_structured_mailing_address_preserves_unit_and_leading_postal_zero():
    result = read_mailing_address(
        profile(["12 Example Ln.", "Unit 7", "Dracut, MA, 01826"])
    )
    assert result is not None
    assert (
        result.line1,
        result.line2,
        result.city,
        result.state,
        result.postal_code,
    ) == ("12 Example Ln.", "Unit 7", "Dracut", "MA", "01826")
    assert result.formatted == "12 Example Ln.\nUnit 7\nDracut, MA, 01826"


def test_incomplete_address_retains_text_but_does_not_invent_mail_ready_fields():
    result = read_mailing_address(profile(["Somewhere near the lake"]))
    assert result is not None and result.formatted == "Somewhere near the lake"
    assert result.city is None and result.postal_code is None


def test_explicit_country_between_region_and_postcode_is_preserved():
    result = read_mailing_address(profile(["12 Example Ln.", "Dracut, MA, US, 01826"]))
    assert result is not None and result.postal_code == "01826"


def test_partial_activity_header_preserves_captured_time_without_inventing_body():
    result = read_timeline_capture(
        ["Note", "1:18 PM", "Created", "By Example Agent"], date(2025, 1, 2)
    )
    assert result.captured_time == "13:18:00"
    assert result.body is None


def test_split_note_fragment_keeps_its_text_but_not_proven_page_footer():
    result = read_timeline_capture(
        [
            "Call",
            "A personal note about a call.",
            "End of Timeline",
            "Welcome to KWIQ",
            "KWIQ uses artificial intelligence (AI).",
        ],
        None,
    )
    assert result.body == "Call\nA personal note about a call."


@pytest.mark.parametrize(
    "lines", [profile(["--"]), ["NOTE", "Mailing Address", "12 Example", "Legal Name"]]
)
def test_no_address_invented_from_placeholder_or_note(lines):
    assert read_mailing_address(lines) is None


def test_only_proven_profile_and_navigation_blocks_are_hidden():
    assert read_timeline_capture(profile(["--"]), None).hidden
    nav = [
        "SmartPlans",
        "2",
        "Tasks",
        "10",
        "Notes",
        "1",
        "Saved Searches",
        "All Time",
        "All Activity",
        "Only Mine",
        "Add Activity",
        "AI Summary",
        "JAN 12, 2026",
    ]
    result = read_timeline_capture(nav, None)
    assert result.hidden and result.next_date == date(2026, 1, 12)
    assert not read_timeline_capture(
        ["NOTE", "Mailing Address", "Legal Name"], None
    ).hidden
    assert not read_timeline_capture(["SMARTPLANS", "Added", "Tasks"], None).hidden


def test_trailing_date_belongs_to_next_event_not_previous_event():
    lines = [
        "EMAIL",
        "1:40 PM",
        "Sent",
        "By Example Agent",
        "An update",
        "From: example@example.test",
        "To: person@example.test",
        "SEP 4, 2025",
    ]
    result = read_timeline_capture(lines, date(2026, 1, 12), has_following_event=True)
    assert result.captured_date == date(2026, 1, 12)
    assert result.captured_time == "13:40:00"
    assert result.next_date == date(2025, 9, 4)
    assert result.title == "An update"
    assert "SEP 4" not in result.body


def test_actual_note_survives_footer_cleanup_and_has_no_fabricated_timezone():
    lines = [
        "Note",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Lake open house",
        "Requested a follow-up.",
        "End of Timeline",
        "\ue90f",
        "Welcome to KWIQ",
        "KWIQ uses artificial intelligence (AI).",
        "Accept",
        "Cancel",
    ]
    result = read_timeline_capture(lines, date(2025, 4, 28))
    assert result.title == "Lake open house"
    assert result.body == "Requested a follow-up."
    assert result.captured_date == date(2025, 4, 28)
    assert result.captured_time == "14:16:00"


def test_unknown_content_and_date_literals_in_note_are_preserved():
    lines = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Dates discussed",
        "SEP 4, 2025",
        "Please call on that date.",
    ]
    result = read_timeline_capture(lines, None)
    assert result.captured_date is None
    assert result.body == "SEP 4, 2025\nPlease call on that date."
    assert result.next_date is None


def test_footer_words_inside_actual_note_are_not_page_controls():
    lines = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Training",
        "Welcome to KWIQ",
        "The client asked about this phrase.",
    ]
    assert "Welcome to KWIQ" in read_timeline_capture(lines, None).body


def test_footer_label_without_actual_footer_signature_is_preserved():
    lines = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Training",
        "End of Timeline",
        "Preserve this message.",
        "Welcome to KWIQ",
        "This is just a note.",
    ]
    assert read_timeline_capture(lines, None).body == "\n".join(lines[5:])


def test_final_date_in_last_note_is_content_not_a_following_day():
    lines = [
        "NOTE",
        "2:16 PM",
        "Created",
        "By Example Agent",
        "Closing appointment",
        "SEP 4, 2025",
        "End of Timeline",
        "Welcome to KWIQ",
        "KWIQ uses artificial intelligence (AI).",
    ]
    result = read_timeline_capture(lines, date(2025, 1, 2))
    assert result.body == "SEP 4, 2025"
    assert result.next_date == date(2025, 1, 2)
