# eXp Brokerage Swap Implementation Plan

> Execution mode: subagent-driven development with independent spec and quality review.

**Goal:** Replace active Keller Williams/KW branding with official eXp Realty branding across SoldWithSweeney while preserving the existing black-and-gold design, page structure, interactions, and lead flows.

**Scope:** Current frontend copy and assets, current project instructions/spec, backend compliance and generation prompts, seed defaults, DB-backed published blogs/funnels/content/link-pack data, and regression coverage. Archived implementation plans and historical task journals remain historical evidence and are not runtime inputs.

## Task 1: Add brokerage regression coverage

**Files:**
- Create: `backend/tests/test_brokerage_branding.py`
- Modify: `backend/tests/test_compliance_disclaimer.py`
- Modify: `backend/tests/test_investor_service_compliance.py`

1. Add a repository scan test covering active frontend/backend source, current instructions/spec, and public asset filenames; fail on Keller Williams, Keller, KW-branded URLs, or removed KW filenames.
2. Update compliance assertions to require `eXp Realty` and reject the old brokerage phrase.
3. Run the targeted tests and confirm they fail before implementation.

## Task 2: Swap active frontend branding without redesigning the site

**Files:**
- Modify: `frontend/src/components/layout/Navbar.tsx`
- Modify: `frontend/src/components/layout/Footer.tsx`
- Modify: `frontend/src/components/home/Hero.tsx`
- Modify: active About, Buy, Sell, Invest, Blog, Blog Article, and Funnel Registration components
- Add: `frontend/public/logos/exp-realty-white.png`
- Add: `frontend/public/logos/exp-realty-source.json`
- Remove: KW-only and SWS/KW composite images under `frontend/public/logos/`

1. Download the approved white transparent eXp Realty logo from the official public eXp brand kit and record its source/checksum.
2. Replace the navbar composite with the existing clean black/gold SWS mark only; use the official white eXp mark in the footer and preserve header height, spacing, colors, and behavior.
3. Replace the footer KW logo, legal URLs, affiliation text, and disclosures with eXp equivalents; remove the KW-specific independent-office phrase.
4. Replace old-brokerage copy on active pages only; do not change layout, palette, typography, animation, or CTAs.

## Task 3: Stop runtime content from reintroducing Keller Williams

**Files:**
- Modify: `backend/services/blog_service.py`
- Modify: `backend/services/funnel_service.py`
- Modify: `backend/services/gemini.py`
- Modify: `backend/services/compliance/disclaimer.py`
- Modify: `backend/seed.py`
- Modify: `backend/scripts/seed_link_pack.py`
- Add: `backend/scripts/migrate_exp_branding.py`
- Add: `frontend/public/assets/link-pack-black-gold-clean.png`

1. Replace old-brokerage prompt/default/disclaimer wording with `eXp Realty` or `brokered by eXp Realty` where disclosure context requires it.
2. Keep the Zapier CRM handoff generic and explicitly legacy; do not invent an eXp CRM integration.
3. Replace the link-page seed background with the cleaned, logo-free black-and-gold background and remove obsolete KW URLs/defaults; retain eXp attribution in profile copy without rendering an eXp logo on `/links`.
4. Implement an idempotent migration with dry-run default, transactional apply mode, backup output, explicit table/field allowlist, and post-update verification for blogs, funnels, content blocks, and link-pack data.
5. Run dry-run first; apply only after reviews pass, then re-query counts to verify zero active old-brokerage matches.

## Task 4: Update current project contract and verify

**Files:**
- Modify: `AGENTS.md`
- Modify: `claude.md`
- Modify: `BRANDON_RE_SPEC.md`
- Append: `tdtn.md`
- Append: `memory.md`

1. Update current brand/CRM instructions so future generation cannot restore KW wording; describe CRM transport generically until an eXp integration is specified.
2. Run targeted backend tests, full backend tests from `backend/.venv`, frontend tests, typecheck, lint, and production build.
3. Run the active-source old-brand scan and verify only explicitly excluded historical records contain old terms.
4. Inspect desktop/mobile navbar, footer, key pages, and `/links`; confirm black/gold styling and interactions are unchanged.
5. Append the task result and verification evidence to the required progress and memory files without overwriting pre-existing edits.
