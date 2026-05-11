# Investor Report Compliance Guardrails — Design

**Date:** 2026-05-11
**Author:** Brainstormed with Claude
**Scope:** Backend — `services/investor_service.py` Gemini-generated reports
**Status:** Draft for review

---

## Problem

`services/investor_service.py` generates a free-text investor report via Gemini Pro. The four free-text fields it returns (`ai_explanation`, `exit_comparison.{sell,refinance,exchange_1031}`, `verdict_reason`) have **no compliance guardrails today**. Three risk surfaces:

1. **Fair Housing Act violations** — Gemini may produce demographic-coded language (steering) or directly reference protected classes (federal FHA + MA Ch. 151B + NH RSA 354-A).
2. **Unauthorized legal/tax/financial advice** — violates NAR Code of Ethics Article 11 (competence within expertise) and Article 13 (no advice outside license).
3. **State-specific legal misstatements** — MA security-deposit law, rent-control claims, lead-paint disclosure, STR legality, etc.

The chatbot prompt already has light guardrails. The investor report has none.

## Goal

Every Gemini-generated investor report returned to a user is **clean by the time it leaves the backend**. Violations are detected, auto-rewritten by a second Gemini call, and the full chain is logged for later analysis.

**Out of scope (this spec):** chatbot, blog generator, admin UI for viewing violations.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Architecture | Prompt rules + deterministic post-check (regex/lexicon) |
| Violation handling | Auto-rewrite via Gemini Flash; log every violation+rewrite |
| Scope | Investor report only (shared `compliance/` module for future reuse) |
| Rule storage | Python constants (type-safe, PR-reviewed, unit-testable) |
| Rule severity tiers | All `hard` for v1 (revisit if false-positive rate too high) |
| Database | Existing Neon Postgres, new table via Alembic |
| Disclaimer | Always appended, regardless of violation status |

---

## Architecture

A new `backend/services/compliance/` module sits between Gemini and the response sent to the user.

```
generate_investor_analysis(inputs, metrics)
  ├─ Build prompt (now with embedded compliance rules section)
  ├─ Call Gemini Pro → parse JSON report
  ├─ compliance.enforce(report, db, lead_id):
  │   ├─ scanner.scan_report(report) → list[Violation]
  │   ├─ for each field with violations:
  │   │    └─ rewriter.rewrite_field(field, original, violations)
  │   │       calls Gemini Flash-Lite; re-scan; retry once max;
  │   │       if still dirty → FALLBACK_STRINGS[field]
  │   ├─ audit.log_violations(db, lead_id, originals, finals, attempts)
  │   └─ report["disclaimer"] = disclaimer.build_disclaimer()
  └─ return cleaned report
```

`investor_service.py` calls one entry point: `await compliance.enforce(report, db=db, lead_id=lead.id)`.

### Module layout

```
backend/services/compliance/
  __init__.py          # exports: enforce()
  rules.py             # PROTECTED_CLASS_TERMS, CODED_PHRASES, ADVICE_PATTERNS, MA_NH_LANDMINES
  prompt.py            # COMPLIANCE_PROMPT_BLOCK constant (string)
  scanner.py           # scan_text(text), scan_report(report) → violations
  rewriter.py          # rewrite_field(field_name, original, violations) — Gemini Flash-Lite
  disclaimer.py        # build_disclaimer() → str
  audit.py             # log_violations(db, ...) — writes ComplianceViolation rows
```

### `Violation` dataclass

```python
@dataclass(frozen=True)
class Violation:
    rule_id: str            # "FH-001", "CP-014", ...
    category: Literal["fair_housing", "coded_phrase", "unauthorized_advice", "state_specific"]
    severity: Literal["hard", "soft"]   # v1: all "hard"
    field_path: str          # "ai_explanation", "exit_comparison.sell", ...
    matched_text: str        # the offending substring
    span: tuple[int, int]    # char offsets in the original field
    guidance: str            # passed to rewriter prompt
```

---

## Rules content (`rules.py`)

Four categories, all as Python data:

### 1. `PROTECTED_CLASS_TERMS`

Words/phrases that reference protected classes per Federal FHA + MA Ch. 151B + NH RSA 354-A. Examples: `"families with children"`, `"no kids"`, `"Christian neighborhood"`, `"section 8"`, `"voucher"`, `"empty nesters"`, `"young couples"`.

Covers: race, color, national origin, religion, sex, familial status, disability (federal), plus age, marital status, sexual orientation, gender identity, source of income, military/veteran status, genetic information, ancestry (MA + NH adds).

### 2. `CODED_PHRASES`

Phrases ruled discriminatory steering by HUD enforcement actions and flagged in NAR "Words to Avoid" guidance. Examples: `"family-friendly"`, `"good for young professionals"`, `"up-and-coming neighborhood"`, `"safe neighborhood"`, `"good schools"`, `"walking distance to churches/temples"`, `"exclusive"`, `"private community"`, `"traditional family"`, `"english speaking"`.

### 3. `ADVICE_PATTERNS`

Regex for unauthorized legal/tax/financial advice (NAR Articles 11, 13). Examples:

```
r"you (will|should) (?:save|owe|pay) \$[\d,]+ in tax"
r"guaranteed (return|profit|appreciation)"
r"(1031|like-kind) exchange (?:will|guarantees) (?:defer|avoid)"
r"this (will|is guaranteed to) appreciate"
r"no need to consult"
```

### 4. `MA_NH_LANDMINES`

State-specific traps. Examples: rent-control claims (banned in MA statewide since 1994 except limited Boston exceptions), security-deposit specifics (MA Ch. 186 §15B → treble damages on wrong advice), lead-paint shortcut claims, eviction timing claims, blanket STR legality (each MA/NH town has its own bylaw).

### Rule shape

```python
@dataclass(frozen=True)
class Rule:
    id: str
    category: Literal["fair_housing", "coded_phrase", "unauthorized_advice", "state_specific"]
    pattern: re.Pattern   # compiled, IGNORECASE
    severity: Literal["hard", "soft"]
    guidance: str          # natural language, passed to rewriter prompt
```

**v1 ships all rules as `hard`.** Soft tier is the v2 lever if false-positive rate is too high.

---

## Scanner + rewriter behavior

### `enforce()` flow

1. **Scan.** Walk fields: `ai_explanation`, `exit_comparison.sell`, `exit_comparison.refinance`, `exit_comparison.exchange_1031`, `verdict_reason`. For each, run every `Rule.pattern.finditer()`. Collect violations.
2. **Group by field.** Zero-violation fields pass through.
3. **Rewrite.** For each violating field: call `rewriter.rewrite_field()` with Gemini Flash-Lite using this prompt template:

   > You are rewriting a section of a real estate investor report to remove specific compliance issues. ORIGINAL: `<text>`. ISSUES: `<bulleted list of violations.guidance>`. Rewrite preserving the analytical meaning. Do NOT mention the original problematic phrasing. Return ONLY the rewritten text, no preamble.

4. **Re-scan the rewrite.** Clean → use it. Dirty → one retry. Still dirty → `FALLBACK_STRINGS[field_name]`. Per-field fallback map lives in `rewriter.py`.

   Example fallback for `ai_explanation`:
   > *"This deal's full narrative analysis is being reviewed by Brandon's team. The numeric metrics above remain valid."*

5. **Log.** Every violation + rewrite attempt persists to `compliance_violations` regardless of final outcome.
6. **Append disclaimer.** Set `report["disclaimer"]` to `build_disclaimer()` output.

### Latency budget

- Zero-violation path: +5–20ms (regex only).
- One violating field: +1 Flash-Lite call (~500–1500ms).
- Worst case (all five fields dirty, both retries needed): +6–10s.

Investor report already takes ~5–15s on Gemini Pro. Acceptable overhead for a once-per-submission flow.

### Failure isolation

If `audit.log_violations()` fails (DB down, schema mismatch), log a structured error and return the cleaned report anyway. Losing a user's 5–15s analysis to an audit-table issue is worse than missing one audit row. Errors go to the existing `logger`.

---

## Disclaimer block (`disclaimer.py`)

Three concatenated blocks, always appended as a separate `disclaimer` field on the report (frontend controls styling — keeps muted footer text out of the analytical paragraphs).

1. **Not-advice (NAR Articles 11, 13 cover):**
   > *This analysis is generated as informational projection only and does not constitute legal, tax, accounting, or investment advice. Consult a licensed attorney, CPA, and your loan officer before acting on any figures.*

2. **Fair Housing (HUD-recommended language):**
   > *Sold With Sweeney & Co. is an Equal Housing Opportunity provider. We comply with the Federal Fair Housing Act and applicable Massachusetts and New Hampshire fair housing laws.*

3. **KW broker disclosure (already required per `CLAUDE.md`, matches existing footer):**
   > *Brandon Sweeney is a licensed real estate agent in MA & NH. Sold With Sweeney & Co. is powered by Keller Williams Realty Success. Each office is independently owned and operated.*

### Updated report shape

```python
{
  "ai_explanation": "...",          # may be a rewritten version
  "hold_scenarios": [...],
  "exit_comparison": {...},
  "sensitivity": {...},
  "verdict": "MODERATE",
  "verdict_reason": "...",
  "disclaimer": "..."               # NEW — always present
}
```

### Frontend change

In `frontend/src/components/investor/FullReportResults.tsx`, render `report.disclaimer` in a `text-white/50 text-xs` block at the bottom of the report card. Add the `disclaimer: string` field to the `Report` type in `frontend/src/components/investor/report-types.ts`. Matches existing footer disclaimer treatment per CLAUDE.md.

---

## Persistence — `compliance_violations` table

New SQLAlchemy model in existing Neon Postgres DB. New Alembic migration.

```python
class ComplianceViolation(Base):
    __tablename__ = "compliance_violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)

    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    source: Mapped[str]                 # "investor_report" (extensible)
    rule_id: Mapped[str]                # "FH-001", "CP-014", ...
    category: Mapped[str]
    severity: Mapped[str]
    field_path: Mapped[str]
    matched_text: Mapped[str]
    original_text: Mapped[str]          # full field value before any rewrite (Text)
    final_text: Mapped[str]             # post-rewrite or fallback value (Text)
    rewrite_attempts: Mapped[int]       # 0, 1, or 2
    resolution: Mapped[str]             # "rewritten_clean" | "rewritten_still_dirty_fallback" | "no_action_needed"
```

**One row per violation**, not per report. A report with 4 violations → 4 rows. Easier to aggregate "all FH hits this month" than to unpack JSON arrays.

Admin view at `/admin/compliance` is **out of scope** for this spec. For v1, rows are queryable via direct DB tools.

---

## Testing strategy

Three layers.

### Layer 1 — unit, scanner & rules (`tests/test_compliance_scanner.py`)

Pure-Python, no network. Fixture pairs in `tests/fixtures/compliance_{bad,good}_sentences.py`:

- ~30 known-bad sentences, each asserts a specific `rule_id` fires.
- ~20 known-good sentences, all assert zero matches. Locks the false-positive baseline.
- Edge cases: case insensitivity, word boundaries (don't match `"exclusive"` inside `"exclusively rented"`), unicode, punctuation.

### Layer 2 — unit, rewriter & enforce (`tests/test_compliance_enforce.py`)

Gemini Flash-Lite is **mocked**. Scenarios:

- Clean report → unchanged + disclaimer appended.
- Single-field violation → rewriter called once with right field + guidance → re-scan clean → final report uses rewrite + audit row written.
- Rewriter returns dirty → second attempt → still dirty → fallback string used → audit row marks `rewritten_still_dirty_fallback`.
- Audit DB write failure → cleaned report still returned, error logged.

### Layer 3 — integration, real Gemini (`tests/test_compliance_integration.py`)

Marked `@pytest.mark.live_llm`. Run with `pytest -m live_llm`. Skipped if `GEMINI_API_KEY` absent.

- **Scenario A — adversarial inputs.** Property submission engineered to invite Fair Housing language (notes field: `"property is in a Christian area, near temples and good schools, great for young families"`). Assert: final report has zero rule matches when re-scanned; audit table has ≥1 row; the original Gemini output (captured) DID contain matches.
- **Scenario B — clean inputs.** Vanilla investor input. Assert: final report clean, zero audit rows for this lead, report quality preserved (`ai_explanation` ≥200 chars, all fields present).
- **Scenario C — rewriter quality smoke.** When a rewrite happens, new text is (a) clean per re-scan, (b) still answers the analytical question (loose keyword preservation, e.g. if original mentioned "cash flow", rewrite should too).

**Coverage target:** unit tests ≥90% on `compliance/` module. Integration tests are pass/fail.

**CI policy:** unit layers run on every push; live-LLM layer runs on demand (manual command) or scheduled nightly — your call when wiring CI.

---

## File changes summary

### New files

```
backend/services/compliance/__init__.py
backend/services/compliance/rules.py
backend/services/compliance/prompt.py
backend/services/compliance/scanner.py
backend/services/compliance/rewriter.py
backend/services/compliance/disclaimer.py
backend/services/compliance/audit.py
backend/db/models/compliance_violation.py
backend/alembic/versions/<hash>_compliance_violations.py

backend/tests/test_compliance_scanner.py
backend/tests/test_compliance_enforce.py
backend/tests/test_compliance_integration.py
backend/tests/fixtures/compliance_bad_sentences.py
backend/tests/fixtures/compliance_good_sentences.py
```

### Modified files

```
backend/services/investor_service.py                            # inject COMPLIANCE_PROMPT_BLOCK, call compliance.enforce()
backend/services/gemini.py                                      # add generate_text_flash_lite() for rewriter
backend/db/models/__init__.py                                   # export ComplianceViolation
frontend/src/components/investor/FullReportResults.tsx          # render report.disclaimer
frontend/src/components/investor/report-types.ts                # add disclaimer: string to Report type
```

### New configuration file

```
backend/pytest.ini    # NEW — registers the live_llm marker (project has no existing pytest config)
```

Contents:

```ini
[pytest]
markers =
    live_llm: integration tests that hit real Gemini API (require GEMINI_API_KEY)
```

### Rollout order

1. `rules.py` + `scanner.py` + unit tests (Layer 1).
2. `rewriter.py` + `disclaimer.py` + `compliance/__init__.py:enforce()` + unit tests (Layer 2).
3. DB model + Alembic migration + `audit.py`.
4. Wire into `investor_service.py` + frontend disclaimer field.
5. Integration tests with real Gemini (Layer 3) — proves end-to-end before merge.

Each step is independently mergeable. The pipeline is dark until step 4 flips the call site — so live-LLM test issues can be tuned without affecting prod.

---

## Open questions

None for v1. Soft-severity rules and admin UI are deliberately deferred.
