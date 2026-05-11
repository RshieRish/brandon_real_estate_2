from unittest.mock import AsyncMock, patch

import pytest

from services.compliance.scanner import Violation


def _v(rule_id: str, field_path: str = "ai_explanation", text: str = "family-friendly") -> Violation:
    return Violation(
        rule_id=rule_id,
        category="coded_phrase",
        severity="hard",
        field_path=field_path,
        matched_text=text,
        span=(0, len(text)),
        guidance="Remove the demographic-coded phrase.",
    )


@pytest.mark.asyncio
async def test_rewrite_field_returns_clean_rewrite_on_first_try():
    from services.compliance.rewriter import rewrite_field

    with patch(
        "services.compliance.rewriter.generate_text_flash_lite",
        new=AsyncMock(return_value="A 3-bedroom property with yard."),
    ) as gen:
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert attempts == 1
    assert resolution == "rewritten_clean"
    gen.assert_awaited_once()


@pytest.mark.asyncio
async def test_rewrite_field_retries_when_first_rewrite_still_dirty():
    from services.compliance.rewriter import rewrite_field

    responses = iter([
        "Still a family-friendly home.",   # still dirty
        "A 3-bedroom property with yard.",  # clean
    ])

    async def fake_gen(prompt: str) -> str:
        return next(responses)

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=fake_gen):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert attempts == 2
    assert resolution == "rewritten_clean"


@pytest.mark.asyncio
async def test_rewrite_field_falls_back_when_two_rewrites_dirty():
    from services.compliance.rewriter import rewrite_field, FALLBACK_STRINGS

    async def always_dirty(prompt: str) -> str:
        return "Still a family-friendly home."

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=always_dirty):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == FALLBACK_STRINGS["ai_explanation"]
    assert attempts == 2
    assert resolution == "rewritten_still_dirty_fallback"


@pytest.mark.asyncio
async def test_rewrite_field_unknown_field_uses_generic_fallback():
    from services.compliance.rewriter import rewrite_field

    async def always_dirty(_: str) -> str:
        return "family-friendly still"

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=always_dirty):
        out, _attempts, resolution = await rewrite_field(
            "some_unmapped_field",
            "family-friendly text",
            [_v("CP-001", field_path="some_unmapped_field")],
        )
    assert "review" in out.lower()  # generic fallback contains the word "review"
    assert resolution == "rewritten_still_dirty_fallback"


@pytest.mark.asyncio
async def test_rewrite_field_handles_gemini_exception_and_continues():
    """Transient Gemini error on attempt 1 should retry, not propagate."""
    from services.compliance.rewriter import rewrite_field

    call_count = {"n": 0}

    async def flaky(prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Gemini 503")
        return "A 3-bedroom property with yard."

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=flaky):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert attempts == 2
    assert resolution == "rewritten_clean"


@pytest.mark.asyncio
async def test_rewrite_field_falls_back_when_all_attempts_error():
    """If every Gemini call errors, use fallback with the error resolution."""
    from services.compliance.rewriter import rewrite_field, FALLBACK_STRINGS

    async def always_error(prompt: str) -> str:
        raise RuntimeError("Gemini quota exceeded")

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=always_error):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == FALLBACK_STRINGS["ai_explanation"]
    assert attempts == 2
    assert resolution == "rewrite_error_fallback"


@pytest.mark.asyncio
async def test_rewrite_field_strips_triple_backtick_fences():
    """Flash-Lite wraps output in ```text...``` — strip before rescan."""
    from services.compliance.rewriter import rewrite_field

    async def fenced(prompt: str) -> str:
        return "```text\nA 3-bedroom property with yard.\n```"

    with patch("services.compliance.rewriter.generate_text_flash_lite", new=fenced):
        out, attempts, resolution = await rewrite_field(
            "ai_explanation",
            "A family-friendly home.",
            [_v("CP-001")],
        )
    assert out == "A 3-bedroom property with yard."
    assert resolution == "rewritten_clean"
