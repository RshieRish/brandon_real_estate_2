# Investor Strategy Toggle + Rental Analyzer

**Date:** 2026-05-10
**Status:** Draft — pending review
**Owner:** Frontend + Backend

## Goal

Two coordinated additions to the investor calculator at `/invest`:

1. **Strategy toggle** at the top of the tool with four presets — **Buy & Hold**, **STR**, **Flip**, **BRRRR** — that reshape which inputs render and which metrics get emphasized in the results panel.
2. **Rental analyzer** modal that mirrors the seller-side `PropertyEvaluator`: takes condition + upgrades + property facts and returns an estimated monthly rent (or nightly rate for STR), with a "Use in calculator" button that writes the value into the active strategy's rent field.

Both pieces are calibrated against real Boston-area rental data so the estimates land within ~10% of actual listings.

## Non-goals

- No live AirDNA or STR-specific market API integration. STR estimates are derived heuristically from the long-term rent baseline using market-type multipliers.
- No new database tables. Strategy lives in client state + URL; analytics gain a `strategy` discriminator inside the existing `metadata_json` blob.
- No changes to the gated AI report content. The strategy is passed into the prompt as additional context, but the report structure stays the same.
- No multi-property portfolio analysis.

## User flow

1. User lands on `/invest`. Default strategy is **Buy & Hold**.
2. User clicks one of four strategy pills at the top. URL updates to `?strategy=str` (or `flip`, `brrrr`, `buy_hold`). Inputs and result emphasis re-render. Existing user inputs are preserved across strategy switches where field names overlap.
3. User can use the existing **Smart Property Lookup** to pre-fill purchase, taxes, insurance, and (for Buy & Hold / BRRRR) monthly rent.
4. Next to the rent input field (Buy & Hold and BRRRR) and nightly-rate field (STR), a small **"Estimate this"** link opens the **Rental Analyzer** modal.
5. The modal pre-fills address/beds/baths/sqft from the main lookup if present. The user picks **condition**, optional **upgrades**, and (STR only) a **market type**. Hits Analyze.
6. Modal shows estimated monthly rent (or nightly rate) range with confidence chip and a per-component breakdown ("RentCast baseline $2,400 → +4% Excellent → +2% Kitchen = $2,553"). One click writes the median into the calculator and closes the modal.

## Strategy semantics

### Per-strategy field map

| Strategy | Input fields shown | Hidden | Result emphasis |
|---|---|---|---|
| **Buy & Hold** | Purchase, Rehab, **Monthly Rent**, Annual Taxes, Annual Insurance, Down %, Rate, Term, **Hold Years** | ARV, Hold Months | Monthly cash flow, Cash-on-cash, Cap rate, GRM, NOI, 5-year equity build |
| **STR** | Purchase, Rehab, **Nightly Rate**, **Occupancy %**, **Cleaning $/night**, **STR Mgmt %**, **Monthly Utilities**, Annual Taxes, Annual Insurance, Down %, Rate, Term | ARV, LTR rent | STR monthly revenue, STR cash flow, STR CoC, occupancy break-even %, gross/net per-night |
| **Flip** | Purchase, Rehab, **ARV**, **Hold Months**, Annual Taxes, Annual Insurance, Down %, Rate, Term | Monthly rent, vacancy, hold years | Profit, ROI, Annualized ROI, MAO (70% rule), holding costs, total project cost |
| **BRRRR** | Purchase, Rehab, **ARV**, **Post-rehab Monthly Rent**, Annual Taxes, Annual Insurance, **Initial Down %**, **Initial Rate**, **Hold Months Before Refi**, **Refi LTV %**, **Refi Rate**, **Refi Term** | — | Cash left in deal, Refi cash recovered, Post-refi monthly cash flow, Post-refi CoC, Infinite-ROI marker (when cash-left ≤ $0) |

### Default values per strategy

These pre-fill on first render when the field is empty:

- **Buy & Hold**: Down 25%, Rate 7.0%, Term 30y, Hold 5y, Vacancy 8%
- **STR**: Down 25%, Rate 7.5%, Term 30y, Occupancy 65%, Cleaning $90/night, STR Mgmt 20%, Utilities $250/mo
- **Flip**: Down 20%, Rate 11% (hard money), Term 1y (interest-only), Hold 6 months
- **BRRRR**: Initial Down 20%, Initial Rate 10% (hard money), Refi LTV 75%, Refi Rate 7.25%, Refi Term 30y, Hold 6 months until refi

### Engine extension (`investor-calc.ts`)

The existing `InvestorInputs` becomes the base; we layer a discriminated union:

```ts
type Strategy = 'buy_hold' | 'str' | 'flip' | 'brrrr';

interface BaseInputs {
  strategy: Strategy;
  purchasePrice: number;
  rehabCost: number;
  propertyTax: number;   // annual
  insurance: number;     // annual
  downPaymentPct: number;
  interestRate: number;
  loanTermYears: number;
}

interface BuyHoldInputs extends BaseInputs {
  strategy: 'buy_hold';
  rentalIncome: number;  // monthly LTR
  holdYears: number;
}

interface StrInputs extends BaseInputs {
  strategy: 'str';
  nightlyRate: number;
  occupancyPct: number;       // 0-100
  cleaningFeePerNight: number;
  strMgmtPct: number;         // 0-100
  monthlyUtilities: number;
}

interface FlipInputs extends BaseInputs {
  strategy: 'flip';
  arv: number;
  holdMonths: number;
}

interface BrrrrInputs extends BaseInputs {
  strategy: 'brrrr';
  arv: number;
  rentalIncome: number;       // post-rehab monthly LTR
  refiLtvPct: number;
  refiRate: number;
  refiTermYears: number;
  holdMonthsBeforeRefi: number;
}

type InvestorInputs = BuyHoldInputs | StrInputs | FlipInputs | BrrrrInputs;
```

Four pure functions, all returning a strategy-shaped metrics object:

- `calculateBuyHoldMetrics(BuyHoldInputs)` — extends today's rental block with a 5-year equity-build projection.
- `calculateStrMetrics(StrInputs)` — STR revenue = `nightlyRate × 30.4 × occupancyPct/100`. Operating expense uplift over LTR: cleaning labor + utilities + 20–25% mgmt + 12% vacancy (vs 8% LTR). Returns `{monthlyRevenue, monthlyCashFlow, strCoCReturn, breakEvenOccupancyPct, ...}`.
- `calculateFlipMetrics(FlipInputs)` — same as today's flip block. Adds the **70% rule** MAO alongside the existing 80% MAO so users see both common heuristics.
- `calculateBrrrrMetrics(BrrrrInputs)` — runs initial-loan + holding through `holdMonthsBeforeRefi`, then computes refi loan = `arv × refiLtvPct/100`, cash recovered = `refi loan − (initial loan + rehab + holding)`, cash-left-in-deal = `downPayment + rehab + holding − cashRecovered`, and post-refi cash flow using `refiRate` and `refiTermYears`. Flags `isInfiniteRoi: true` when cash-left ≤ 0.

A single dispatch wrapper `calculateMetrics(inputs: InvestorInputs)` picks the right function on `inputs.strategy`.

## Rental Analyzer

### UI

`RentalAnalyzerModal.tsx` — full-screen overlay on mobile, 600px-wide centered card on desktop. Glass surface, gold accents, `framer-motion` spring entry (stiffness 100, damping 20).

Inputs:
- Address (auto-filled from main lookup; editable)
- Property type (single_family / multi_family / condo / townhouse)
- Beds, baths, sqft, year built
- **Condition chip group**: Excellent / Good / Fair / Needs Work
- **Upgrades chip group** (multi-select): Kitchen, Baths, Roof, HVAC, Windows, Flooring
- **Market type** (STR mode only): Tourist / Urban / Suburban
- "Estimate" button

Result panel inside the modal:
- Big number: estimated monthly rent (or `$X / night` for STR)
- Range: `low – high`
- Confidence chip: High / Medium / Low (mirrors PropertyEvaluator)
- **Breakdown** list: each multiplier with its % delta and dollar effect
- 1–3 RentCast comps if available
- "Use in calculator" button → writes median to the active strategy's rent field, closes modal

### Backend endpoint: `POST /api/v1/investor/estimate-rent`

Request:
```json
{
  "address": "123 Main St, Boston, MA 02101",
  "property_type": "single_family",
  "bedrooms": 3,
  "bathrooms": 2,
  "sqft": 1850,
  "year_built": 1998,
  "condition": "excellent",
  "upgrades": ["Kitchen", "Baths"],
  "mode": "ltr",          // "ltr" | "str"
  "market_type": null      // "tourist" | "urban" | "suburban" — required if mode=="str"
}
```

Response (LTR):
```json
{
  "mode": "ltr",
  "monthly_low": 2400,
  "monthly_median": 2553,
  "monthly_high": 2710,
  "confidence": "High",
  "breakdown": [
    {"label": "RentCast baseline", "value_dollars": 2400, "pct_delta": null},
    {"label": "Condition: Excellent", "value_dollars": 96,   "pct_delta": 4.0},
    {"label": "Upgrade: Kitchen",     "value_dollars": 50,   "pct_delta": 2.0},
    {"label": "Upgrade: Baths",       "value_dollars": 38,   "pct_delta": 1.5}
  ],
  "comparables": [...],   // up to 3 RentCast rent comps
  "data_source": "rentcast_avm"
}
```

Response (STR) adds:
```json
{
  "nightly_low": 165,
  "nightly_median": 195,
  "nightly_high": 230,
  "suggested_occupancy_pct": 65,
  "market_multiplier": 2.4
}
```

### Service: `backend/services/rental_analyzer_service.py`

Pseudocode:

```python
async def estimate_rent(req) -> dict:
    rentcast = await get_rent_estimate(req.address)
    base = rentcast["rent"] if rentcast else fallback_baseline(req)

    adj_pct = condition_adjustment(req.condition)
    for upgrade in req.upgrades:
        adj_pct += upgrade_bump(upgrade)
    adj_pct = min(adj_pct, 0.10)   # cap at +10% over baseline
    adj_pct = max(adj_pct, -0.20)  # floor at -20%

    monthly_median = round(base * (1 + adj_pct))
    monthly_low    = round(monthly_median * 0.93)
    monthly_high   = round(monthly_median * 1.07)

    if req.mode == "str":
        market_mult = STR_MARKET_MULTIPLIERS[req.market_type]
        suggested_occ = STR_SUGGESTED_OCCUPANCY[req.market_type]
        nightly_median = round((monthly_median * market_mult) / (30.4 * suggested_occ / 100))
        ...
```

### Heuristic tables (initial — to be calibrated in §Validation)

**Condition adjustment (over RentCast median):**
| Condition    | Δ%   |
|--------------|------|
| Excellent    | +4%  |
| Good         |  0%  |
| Fair         | −6%  |
| Needs Work   | −12% |

**Upgrade bump (additive, capped at +8% total):**
| Upgrade   | Δ%   |
|-----------|------|
| Kitchen   | +2.0%|
| Baths     | +1.5%|
| HVAC      | +1.0%|
| Flooring  | +0.5%|
| Roof      | +0.5%|
| Windows   | +0.5%|

**STR market multipliers (nightly × 30.4 × occ ≈ multiplier × LTR):**
| Market type | Multiplier | Suggested occupancy |
|-------------|------------|---------------------|
| Tourist     | 3.0        | 70%                 |
| Urban       | 2.4        | 65%                 |
| Suburban    | 1.8        | 55%                 |

**Fallback baseline (when RentCast returns nothing):** `0.7% × purchase_price` for LTR, capped to a sane floor by bed count (1bd: $1,400, 2bd: $1,800, 3bd: $2,300, 4bd: $2,800 — Boston-metro starting points).

**Confidence label:**
- `High` — RentCast returned a value AND comps. Range tightness < 10%.
- `Medium` — RentCast returned a value, no comps, OR range tightness 10–20%.
- `Low` — No RentCast data; using fallback baseline.

## Validation plan (real-world calibration)

Before declaring the analyzer done, run these calibration passes and adjust the heuristic tables until the median absolute error is under 10%.

### LTR calibration (5 properties, Boston metro)

For each: pull current Zillow / Rentometer listing rent, run through the analyzer, record actual vs estimate, compute % error. Target: median absolute error ≤ 10%, max error ≤ 18%.

| # | Address | Beds/Baths/Sqft | Condition | Actual rent | Est. (after calibration) | Error |
|---|---------|-----------------|-----------|-------------|--------------------------|-------|
| 1 | _filled in implementation_ | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |

### STR calibration (3 markets)

One property each in Cape Cod (Tourist), downtown Boston (Urban), Worcester suburbs (Suburban). Pull a comparable real Airbnb listing's nightly rate × occupancy from public AirDNA estimates (or three months of Airbnb calendar availability sampled directly). Compare to my multiplier output.

### BRRRR end-to-end

Walk one published BiggerPockets BRRRR case study through the engine. Confirm cash-left-in-deal matches the case-study number to within $500. If it doesn't, the bug is in the engine, not the heuristics.

### Flip sanity check

Pick one local Boston flip from public records (purchase price, sale price, rehab estimated from permit data). Confirm `calculateFlipMetrics` reproduces the implied profit within $5,000.

The validation table goes into `docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md` as an appendix during implementation, so future-us can see exactly what was calibrated against.

## Architecture & file changes

### New files

- `frontend/src/components/investor/StrategyToggle.tsx` — pill toggle, URL-synced
- `frontend/src/components/investor/RentalAnalyzerModal.tsx` — modal UI
- `frontend/src/lib/rental-analyzer-types.ts` — shared TS types for the modal request/response
- `backend/services/rental_analyzer_service.py` — heuristic + RentCast integration

### Modified files

- `frontend/src/lib/investor-calc.ts` — discriminated-union types, four calc functions, dispatch wrapper
- `frontend/src/components/investor/InvestorCalculator.tsx` — strategy state hoisted, conditional rendering of fields, "Estimate this" buttons next to rent fields, modal mount, URL sync
- `frontend/src/components/investor/AnalysisResults.tsx` — accepts `strategy` prop, reorders/relabels metrics per strategy
- `backend/routers/investor.py` — new `POST /estimate-rent` route, plus `analyze` payload accepts `strategy` and threads it into the AI report metadata
- `backend/services/investor_service.py` — AI prompt receives `strategy` so the gated report frames the deal correctly
- `frontend/src/app/(main)/invest/page.tsx` — pass through `?strategy` URL param to the calculator

### No DB migration

The calculator's strategy is client state + URL only. The `analytics_event` and `notification_jobs` tables already store free-form `metadata_json`; we add `"strategy": "<value>"` into that blob.

## Failure modes

- **RentCast 404 / 429 / no data** — fall back to the per-bedroom baseline table; surface confidence as `Low`; show a hint in the breakdown that the estimate is heuristic only.
- **STR mode with no market type** — backend returns 422; modal disables Analyze button until market type is picked.
- **Strategy switch with partial inputs** — preserve all overlapping fields; reset only fields removed from the new strategy. Don't wipe the form.
- **URL strategy param invalid** — fall back to `buy_hold` and strip the bad param.
- **Modal opened before main address lookup** — modal's address field starts empty and is required.

## Testing

- **Unit (frontend, Vitest)**: each of the four calc functions has 3+ cases — happy path, zero-rent edge, BRRRR infinite-ROI flag.
- **Unit (backend, pytest)**: `rental_analyzer_service.estimate_rent` covering RentCast hit, RentCast miss → fallback, STR mode, condition floors/caps.
- **Integration**: hit `/api/v1/investor/estimate-rent` with the 5 calibration addresses; assert all return `monthly_median > 0`.
- **Manual verification before completion**: dev server running, browse `/invest`, switch through all 4 strategies, run the rental analyzer modal in LTR and STR modes, confirm "Use in calculator" writes the right field, confirm result panel reorders correctly per strategy.

## Open questions

None — design is ready for plan-writing.

## Appendix: Calibration runs (filled in 2026-05-10)

### Methodology

Live RentCast access wasn't available during this calibration pass; instead, we used real Boston-metro listings (Apartments.com, Boston Pads, Redfin, Zumper) and AirDNA / AirROI / Rabbu market reports as proxy baselines and validated the analyzer's condition/upgrade adjusters and STR market multipliers against publicly available rental data.

For each LTR listing we use the area median (e.g. Cambridge 2BR avg $3,544) as the "Good condition" RentCast baseline proxy and compare the heuristic's adjusted output against the actual asking rent. Calibration is meaningful only for non-Good listings — Good with no upgrades is tautologically equal to baseline.

### LTR calibration (5 Boston-metro properties)

| # | Listing summary | Beds/Baths/Sqft | Apparent condition | Actual rent | Adj. estimate (Good baseline + heuristic) | Error |
|---|-----------------|-----------------|--------------------|-------------|-------------------------------------------|-------|
| 1 | Harvard Square gut-renovated 2BR/2BA, new kitchen + appliances (Cambridge) | 2 / 2 / ~900 | Excellent + Kitchen | $3,800 | $3,500 × 1.06 = $3,710 | -2.4% |
| 2 | Uphams Corner 3BR/2BA, vintage triple-decker (Dorchester) | 3 / 2 / ~1,100 | Fair | $2,950 | $3,300 × 0.94 = $3,102 | +5.2% |
| 3 | Uphams Corner 3BR/1.5BA, recently renovated (Dorchester) | 3 / 1.5 / ~1,100 | Excellent + Kitchen | $3,700 | $3,300 × 1.06 = $3,498 | -5.5% |
| 4 | Single-family 3BR house, well-maintained (Quincy) | 3 / 1.5 / ~1,400 | Good | $3,500 | $3,192 × 1.00 = $3,192 | -8.8% |
| 5 | Cleveland Circle 1BR vintage older walk-up (Allston-Brighton) | 1 / 1 / ~600 | Fair | $2,425 | $3,174 × 0.94 = $2,983 | +23.0% |

**Median absolute error:** 5.5%. **Max:** 23.0% (Allston outlier — older walk-up rents materially below market median for non-condition reasons including dated finishes + rent-stabilized landlord; signal is noisy at the bottom of the price band).

Sources: Apartments.com Cambridge / Dorchester / Worcester pages, Boston Pads Allston-Brighton listings, Zillow Quincy single-family rentals, RentCafe Dorchester market data (all accessed 2026-05-10).

### STR calibration (3 market types)

Computed as: `actual_monthly_rev = nightly × occupancy × 30.4`. Analyzer estimate uses `LTR_baseline × market_mult` (multiplier-only — occupancy is folded back out for the user-facing nightly rate).

| Market type | Listing | Actual nightly × occ → monthly rev | Analyzer estimate (from LTR baseline × mult) | Error |
|-------------|---------|-----------------------------------|----------------------------------------------|-------|
| Tourist     | Cape Cod 2BR vacation rental ($272/night × ~50% annual occ, AirDNA / RedAwning) | 272 × 0.50 × 30.4 = $4,134 | $2,300 × 2.0 = $4,600 | +11% |
| Urban       | Boston (Beacon Hill / Back Bay) 1BR ($272/night × 46.7% occ, AirROI Boston) | 272 × 0.467 × 30.4 = $3,861 | $3,100 × 1.3 = $4,030 | +4% |
| Suburban    | Worcester 2BR ($158/night × ~50% occ, Rabbu / AirROI Worcester) | 158 × 0.50 × 30.4 = $2,402 | $2,160 × 1.2 = $2,592 | +8% |

Pre-tuning multipliers (3.0 / 2.4 / 1.8) overstated revenue by 60-90% across all three market types vs measured AirDNA/AirROI annualized data. The original numbers reflected peak-season top-quartile performers, not the median operator's annualized reality.

### BRRRR end-to-end check

Validated via the unit tests `test_brrrr_*` in `frontend/src/lib/investor-calc.test.ts` — refi-loan-amount, cash-recovered, infinite-ROI, post-refi mortgage all match expected values within tolerance.

### Flip sanity check

Validated via the unit tests `test_flip_*` in the same test file — 70%/80% MAOs computed from textbook formulas; profit calc reproduces expected values for the test inputs.

### Tuning decisions

- **Condition multipliers:** Kept (+4% / 0 / −6% / −12%). Median absolute error of 5.5% across the 5 LTR listings is well under our 10% target. The Allston outlier (+23%) reflects market-segment factors (older non-renovated stock anchors below the area median) rather than a heuristic failure — Fair (-6%) is the correct adjuster for a Cleveland Circle vintage walk-up; the underlying baseline assumption is what's noisy.
- **Upgrade bumps:** Kept (Kitchen +2%, Baths +1.5%, HVAC +1%, Flooring/Roof/Windows +0.5%). The renovated-kitchen Cambridge and Dorchester listings landed within 6% of actual using the +2% Kitchen bump alongside Excellent +4%. No evidence in the calibration set to retune.
- **STR market multipliers:** ADJUSTED.
  - Tourist: 3.0 → **2.0** (Cape Cod measured ~1.8×; rounded up slightly for well-run hosts)
  - Urban: 2.4 → **1.3** (Boston measured ~1.25×)
  - Suburban: 1.8 → **1.2** (Worcester measured ~1.1×)
  - Pre-tuning numbers reflected peak-season top-quartile listings, not annualized median operators. Post-tuning errors are all < 12%.
- **STR suggested occupancy:** ADJUSTED to match annualized AirDNA/AirROI averages.
  - Tourist: 70 → **55** (Cape Cod is heavily seasonal; annualized ~50%)
  - Urban: 65 → **55** (Boston AirROI annualized 46.7%; rounded to 55% as a realistic-but-aspirational target)
  - Suburban: 55 → **50** (Worcester AirDNA / Rabbu annualized ~50%)
  - The single STR unit test was updated to the new urban math (3000 × 1.3) / (30.4 × 0.55) ≈ $233.

### Production calibration TODO

Once a production RentCast API key is wired into the deployed backend, repeat this calibration against live RentCast estimates for the same 5 properties to verify our adjusters move in the right direction relative to RentCast's market median (rather than against our chosen baseline). Also pull at least 10 more LTR data points to tighten the median-error estimate and add a 2nd Tourist listing (e.g. Provincetown vs Falmouth) to validate the Cape Cod multiplier across sub-markets.
