"""Rewriter for compliance violations.

When the scanner flags a field, ``rewrite_field`` calls Gemini Flash-Lite with
a focused prompt to produce a clean replacement. If two attempts still violate
the rules, the per-field fallback string is used instead. Returns the final
text plus metadata for audit logging.
"""

from __future__ import annotations

from services.compliance.scanner import Violation, scan_text
from services.gemini import generate_text_flash_lite

MAX_REWRITE_ATTEMPTS = 2

FALLBACK_STRINGS: dict[str, str] = {
    "ai_explanation": (
        "This deal's full narrative analysis is being reviewed by Brandon's team. "
        "The numeric metrics above remain valid."
    ),
    "exit_comparison.sell": (
        "Sell-at-end-of-hold projections are under review. Refer to the numeric "
        "exit value in the hold scenarios above."
    ),
    "exit_comparison.refinance": (
        "Refinance scenario commentary is under review. The cash-flow and LTV "
        "figures above remain valid."
    ),
    "exit_comparison.exchange_1031": (
        "1031 exchange considerations are highly fact-specific — Brandon's team "
        "will review with a qualified intermediary and CPA before any action."
    ),
    "verdict_reason": (
        "The verdict above is supported by the numeric metrics. A detailed "
        "narrative is under review."
    ),
}

_GENERIC_FALLBACK = (
    "This section is being reviewed by Brandon's team. The numeric metrics "
    "above remain valid."
)


def _build_prompt(field_name: str, original_text: str, violations: list[Violation]) -> str:
    issues = "\n".join(f"- {v.guidance}" for v in violations)
    return (
        "You are rewriting a section of a real estate investor report to remove "
        "specific compliance issues.\n\n"
        f"FIELD: {field_name}\n"
        f"ORIGINAL:\n{original_text}\n\n"
        f"ISSUES TO FIX:\n{issues}\n\n"
        "Rewrite the section preserving the analytical meaning. Do NOT mention "
        "the original problematic phrasing. Do NOT add disclaimers. Return ONLY "
        "the rewritten text — no preamble, no commentary, no markdown fences."
    )


def _strip_artifacts(text: str) -> str:
    """Strip common Flash-Lite output artifacts: code fences, leading preambles.

    Flash-Lite occasionally wraps output in triple-backtick fences (with or
    without a language tag) despite prompt instructions, and may add a leading
    'Here is the rewrite:' line. We can't catch every preamble shape, but the
    common cases are cheap to remove before rescanning.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # drop opening fence (with optional language)
        lines = lines[1:]
        # drop closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


async def rewrite_field(
    field_name: str,
    original_text: str,
    violations: list[Violation],
) -> tuple[str, int, str]:
    """Rewrite ``original_text`` to clear ``violations``.

    Returns ``(final_text, attempts, resolution)`` where ``resolution`` is one of:
    ``"rewritten_clean"``, ``"rewritten_still_dirty_fallback"``, or
    ``"rewrite_error_fallback"`` (when every Gemini call errored).
    """
    attempts = 0
    current_text = original_text
    current_violations = violations
    last_error: Exception | None = None

    while attempts < MAX_REWRITE_ATTEMPTS:
        attempts += 1
        prompt = _build_prompt(field_name, current_text, current_violations)
        try:
            raw = await generate_text_flash_lite(prompt)
        except Exception as exc:  # noqa: BLE001 — we explicitly want to swallow & retry
            last_error = exc
            continue
        rewrite = _strip_artifacts(raw)
        rescan = scan_text(field_name, rewrite)
        if not rescan:
            return rewrite, attempts, "rewritten_clean"
        current_text = rewrite
        current_violations = rescan

    fallback = FALLBACK_STRINGS.get(field_name, _GENERIC_FALLBACK)
    resolution = "rewrite_error_fallback" if last_error is not None and current_text == original_text else "rewritten_still_dirty_fallback"
    return fallback, attempts, resolution
