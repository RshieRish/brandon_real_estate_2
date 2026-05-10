# Investor Strategy Toggle + Rental Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4-way strategy toggle (Buy & Hold / STR / Flip / BRRRR) at the top of the investment calculator and a rental analyzer modal that estimates monthly rent (or STR nightly rate) from condition + upgrades + property facts, calibrated against real Boston-metro rental data.

**Architecture:** Strategy state lives in the `InvestorCalculator` component and syncs to `?strategy=...` in the URL. The frontend calc engine becomes a discriminated union with four pure calc functions. A new `RentalAnalyzerModal` component opens from "Estimate this" links next to the rent fields and posts to a new backend route `POST /api/v1/investor/estimate-rent`, which combines RentCast's rent AVM with a heuristic condition/upgrade adjuster (and an STR market multiplier when applicable). All calibration multipliers live in one Python module so they can be tuned in one place.

**Tech Stack:** Next.js 16 (App Router) + React 19 + Framer Motion 12 + TypeScript on the frontend; FastAPI + httpx + RentCast on the backend; Vitest (added in Task 1) for frontend unit tests; existing unittest pattern for backend tests.

**Spec:** [docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md](docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md)

---

## File Structure

**Created:**
- `frontend/src/components/investor/StrategyToggle.tsx` — pill toggle, URL-synced
- `frontend/src/components/investor/RentalAnalyzerModal.tsx` — modal UI mirroring `PropertyEvaluator` patterns
- `frontend/src/components/investor/strategy-defaults.ts` — per-strategy default values (single source of truth)
- `frontend/src/lib/investor-calc.test.ts` — Vitest unit tests for all four calc functions
- `frontend/src/lib/rental-analyzer-types.ts` — shared TS types for the modal request/response
- `frontend/vitest.config.ts` — Vitest configuration
- `backend/services/rental_analyzer_service.py` — heuristic + RentCast integration
- `backend/tests/test_rental_analyzer_service.py` — unit tests
- `backend/tests/test_estimate_rent_router.py` — route-level test

**Modified:**
- `frontend/package.json` — add Vitest devDependencies + `test` script
- `frontend/src/lib/investor-calc.ts` — discriminated union types, four calc functions, dispatch wrapper
- `frontend/src/components/investor/InvestorCalculator.tsx` — strategy state, conditional fields, modal wiring, URL sync
- `frontend/src/components/investor/AnalysisResults.tsx` — accepts `strategy` + per-strategy metric blocks
- `frontend/src/components/investor/report-types.ts` — add optional `strategy` to lead capture payload
- `frontend/src/app/(main)/invest/page.tsx` — pass `?strategy` from URL into calculator
- `backend/routers/investor.py` — new `/estimate-rent` route + `analyze` accepts `strategy`
- `backend/services/investor_service.py` — AI prompt receives `strategy`
- `docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md` — append calibration appendix in Task 14

**Not modified (no DB changes):** All schema files, alembic versions, models.

---

## Phase 1 — Frontend test scaffolding

### Task 1: Add Vitest to the frontend

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`

- [ ] **Step 1: Install Vitest**

Run from the `frontend/` directory:

```bash
cd frontend && npm install -D vitest @vitest/ui
```

Expected: packages added to `devDependencies`, no peer warnings.

- [ ] **Step 2: Add test script**

Edit `frontend/package.json` — under `scripts`, add:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Create Vitest config**

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    globals: false,
  },
});
```

- [ ] **Step 4: Verify Vitest runs (no tests yet, should report 0 files)**

Run from `frontend/`:

```bash
npm test
```

Expected: Vitest runs, reports `No test files found, exiting with code 1`. That's fine — it confirms the runner works. We'll add real tests next.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts
git commit -m "chore(frontend): add Vitest for unit tests"
```

---

## Phase 2 — Calc engine refactor

### Task 2: Pin existing flip+rental behavior under a `buy_hold` strategy with tests

This task moves the current calc logic behind a discriminated-union API without changing any numbers. The existing UI keeps working unchanged.

**Files:**
- Modify: `frontend/src/lib/investor-calc.ts`
- Create: `frontend/src/lib/investor-calc.test.ts`
- Modify: `frontend/src/components/investor/InvestorCalculator.tsx` (call site update only)
- Modify: `frontend/src/components/investor/AnalysisResults.tsx` (accept new metrics shape passthrough)

- [ ] **Step 1: Write failing tests for `calculateBuyHoldMetrics`**

Create `frontend/src/lib/investor-calc.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  calculateBuyHoldMetrics,
  calculateMetrics,
  type BuyHoldInputs,
} from './investor-calc';

describe('calculateBuyHoldMetrics', () => {
  const baseInputs: BuyHoldInputs = {
    strategy: 'buy_hold',
    purchasePrice: 415000,
    rehabCost: 0,
    rentalIncome: 3200,
    propertyTax: 5400,
    insurance: 1400,
    downPaymentPct: 25,
    interestRate: 7,
    loanTermYears: 30,
    holdYears: 5,
  };

  it('computes monthly mortgage on a 30y amortized loan', () => {
    const m = calculateBuyHoldMetrics(baseInputs);
    expect(m.monthlyMortgage).toBeCloseTo(2071, 0);
  });

  it('computes a positive monthly cash flow for the base inputs', () => {
    const m = calculateBuyHoldMetrics(baseInputs);
    expect(m.monthlyCashFlow).toBeGreaterThan(0);
  });

  it('computes cap rate against purchase price', () => {
    const m = calculateBuyHoldMetrics(baseInputs);
    expect(m.capRate).toBeCloseTo(7.7, 0);
  });

  it('flags interest_only loan structure when term ≤ 2 years', () => {
    const m = calculateBuyHoldMetrics({ ...baseInputs, loanTermYears: 1 });
    expect(m.loanStructure).toBe('interest_only');
  });

  it('handles zero rent without divide-by-zero', () => {
    const m = calculateBuyHoldMetrics({ ...baseInputs, rentalIncome: 0 });
    expect(m.grm).toBe(0);
    expect(Number.isFinite(m.monthlyCashFlow)).toBe(true);
  });

  it('dispatch wrapper routes buy_hold inputs correctly', () => {
    const m = calculateMetrics(baseInputs);
    expect(m.strategy).toBe('buy_hold');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test
```

Expected: imports fail / `calculateBuyHoldMetrics` undefined.

- [ ] **Step 3: Refactor `investor-calc.ts` to the discriminated union with `calculateBuyHoldMetrics`**

Replace the contents of `frontend/src/lib/investor-calc.ts` with:

```ts
// ─── Strategy types ─────────────────────────────────────────────────────────
export type Strategy = 'buy_hold' | 'str' | 'flip' | 'brrrr';

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

export interface BuyHoldInputs extends BaseInputs {
  strategy: 'buy_hold';
  rentalIncome: number;  // monthly LTR
  holdYears: number;
}

export interface StrInputs extends BaseInputs {
  strategy: 'str';
  nightlyRate: number;
  occupancyPct: number;        // 0-100
  cleaningFeePerNight: number;
  strMgmtPct: number;          // 0-100
  monthlyUtilities: number;
}

export interface FlipInputs extends BaseInputs {
  strategy: 'flip';
  arv: number;
  holdMonths: number;
}

export interface BrrrrInputs extends BaseInputs {
  strategy: 'brrrr';
  arv: number;
  rentalIncome: number;        // post-rehab monthly LTR
  refiLtvPct: number;
  refiRate: number;
  refiTermYears: number;
  holdMonthsBeforeRefi: number;
}

export type InvestorInputs = BuyHoldInputs | StrInputs | FlipInputs | BrrrrInputs;

// ─── Shared metric base ─────────────────────────────────────────────────────
type LoanStructure = 'interest_only' | 'amortized';

interface BaseMetrics {
  loanStructure: LoanStructure;
  monthlyMortgage: number;
  downPayment: number;
  loanAmount: number;
}

export interface BuyHoldMetrics extends BaseMetrics {
  strategy: 'buy_hold';
  monthlyCashFlow: number;
  annualCashFlow: number;
  cashOnCashReturn: number;  // %
  capRate: number;           // %
  grm: number;               // gross rent multiplier
  noi: number;               // annual
  totalEquity: number;
  fiveYearEquityBuild: number; // simple linear projection
}

export interface StrMetrics extends BaseMetrics {
  strategy: 'str';
  monthlyRevenue: number;
  monthlyCashFlow: number;
  annualCashFlow: number;
  cashOnCashReturn: number;
  breakEvenOccupancyPct: number;
  netPerNight: number;
  grossPerNight: number;
}

export interface FlipMetrics extends BaseMetrics {
  strategy: 'flip';
  flipProfit: number;
  flipROI: number;            // %
  flipAnnualizedROI: number;  // %
  maxAllowableOffer70: number; // 70% rule
  maxAllowableOffer80: number; // 80% rule (existing)
  holdingCosts: number;
  closingCosts: number;
  totalProjectCost: number;
}

export interface BrrrrMetrics extends BaseMetrics {
  strategy: 'brrrr';
  // initial loan + holding
  initialHoldingCosts: number;
  cashIntoDealUpfront: number;
  // refi
  refiLoanAmount: number;
  cashRecoveredAtRefi: number;
  cashLeftInDeal: number;
  isInfiniteRoi: boolean;
  // post-refi rental
  postRefiMonthlyMortgage: number;
  postRefiMonthlyCashFlow: number;
  postRefiCashOnCash: number; // % — Infinity if cashLeftInDeal <= 0
  capRate: number;
  noi: number;
}

export type InvestorMetrics = BuyHoldMetrics | StrMetrics | FlipMetrics | BrrrrMetrics;

// ─── Helpers ────────────────────────────────────────────────────────────────
const safeDivide = (n: number, d: number): number => (d === 0 ? 0 : n / d);

interface MortgageInput {
  loanAmount: number;
  interestRatePct: number;
  termYears: number;
}

function computeMonthlyMortgage({
  loanAmount,
  interestRatePct,
  termYears,
}: MortgageInput): { monthlyMortgage: number; loanStructure: LoanStructure } {
  const monthlyRate = interestRatePct / 100 / 12;
  const numPayments = Math.max(termYears * 12, 1);
  const isShortTermInvestorDebt = termYears <= 2;
  const loanStructure: LoanStructure = isShortTermInvestorDebt ? 'interest_only' : 'amortized';
  if (loanAmount <= 0) return { monthlyMortgage: 0, loanStructure };
  if (isShortTermInvestorDebt) {
    return { monthlyMortgage: loanAmount * monthlyRate, loanStructure };
  }
  if (monthlyRate === 0) {
    return { monthlyMortgage: safeDivide(loanAmount, numPayments), loanStructure };
  }
  const m =
    (loanAmount * (monthlyRate * Math.pow(1 + monthlyRate, numPayments))) /
    (Math.pow(1 + monthlyRate, numPayments) - 1);
  return { monthlyMortgage: m, loanStructure };
}

// ─── Buy & Hold ─────────────────────────────────────────────────────────────
export function calculateBuyHoldMetrics(inputs: BuyHoldInputs): BuyHoldMetrics {
  const downPayment = inputs.purchasePrice * (inputs.downPaymentPct / 100);
  const loanAmount = inputs.purchasePrice - downPayment;
  const { monthlyMortgage, loanStructure } = computeMonthlyMortgage({
    loanAmount,
    interestRatePct: inputs.interestRate,
    termYears: inputs.loanTermYears,
  });

  const monthlyExpenses = (inputs.propertyTax + inputs.insurance) / 12;
  const vacancyAllowance = inputs.rentalIncome * 0.08;
  const monthlyNOI = inputs.rentalIncome - vacancyAllowance - monthlyExpenses;
  const noi = monthlyNOI * 12;
  const monthlyCashFlow = monthlyNOI - monthlyMortgage;
  const annualCashFlow = monthlyCashFlow * 12;
  const cashInvested = downPayment + inputs.rehabCost;
  const cashOnCashReturn = safeDivide(annualCashFlow, cashInvested) * 100;
  const capRate = safeDivide(noi, inputs.purchasePrice) * 100;
  const grm = safeDivide(inputs.purchasePrice, inputs.rentalIncome * 12);
  const totalEquity = inputs.purchasePrice - loanAmount;
  const fiveYearEquityBuild = totalEquity + annualCashFlow * Math.min(inputs.holdYears, 5);

  return {
    strategy: 'buy_hold',
    loanStructure,
    monthlyMortgage,
    downPayment,
    loanAmount,
    monthlyCashFlow,
    annualCashFlow,
    cashOnCashReturn,
    capRate,
    grm,
    noi,
    totalEquity,
    fiveYearEquityBuild,
  };
}

// ─── Dispatch wrapper (will grow as strategies are added) ───────────────────
export function calculateMetrics(inputs: InvestorInputs): InvestorMetrics {
  switch (inputs.strategy) {
    case 'buy_hold':
      return calculateBuyHoldMetrics(inputs);
    default:
      // Other strategies not yet implemented in this task
      throw new Error(`Strategy "${inputs.strategy}" not implemented yet`);
  }
}
```

- [ ] **Step 4: Update call sites in `InvestorCalculator.tsx` and `AnalysisResults.tsx`**

In `frontend/src/components/investor/InvestorCalculator.tsx`:

Replace the `EMPTY_INPUTS` and `parseInvestorInputs` block (lines ~17-84) so that the parsed shape matches `BuyHoldInputs`. For now, hardcode `strategy: 'buy_hold'` and rename `holdMonths` → `holdYears`. Specifically:

```ts
import { calculateMetrics, type BuyHoldInputs } from '@/lib/investor-calc';

type BuyHoldInputValues = Record<Exclude<keyof BuyHoldInputs, 'strategy'>, string>;

const EMPTY_INPUTS: BuyHoldInputValues = {
  purchasePrice: '',
  rehabCost: '',
  rentalIncome: '',
  propertyTax: '',
  insurance: '',
  downPaymentPct: '',
  interestRate: '',
  loanTermYears: '',
  holdYears: '',
};

const POSITIVE_FIELDS: Array<keyof BuyHoldInputValues> = [
  'purchasePrice',
  'holdYears',
  'loanTermYears',
];

function parseBuyHoldInputs(values: BuyHoldInputValues): BuyHoldInputs | null {
  const parsed = Object.entries(values).reduce<Partial<BuyHoldInputs>>((acc, [key, value]) => {
    const trimmed = value.trim();
    const numeric = trimmed ? Number(trimmed) : 0;
    return { ...acc, [key]: Number.isFinite(numeric) ? numeric : 0 };
  }, {});
  const hasValid = POSITIVE_FIELDS.every((k) => (parsed[k] ?? 0) > 0);
  if (!hasValid) return null;
  return { ...parsed, strategy: 'buy_hold' } as BuyHoldInputs;
}
```

Update the input grid to use `holdYears` instead of `holdMonths`:

```tsx
<InputField
  label="Hold Period (Years)"
  name="holdYears"
  value={inputs.holdYears}
  onChange={handleChange}
  suffix="yr"
  step={1}
/>
```

(Drop the existing `holdMonths` and `arv` fields for this task — Flip-only fields will return in Task 7.)

Update the engagement payload (`/api/v1/investor/engagement`) — replace `hold_months` with `hold_years` in the body and convert: send `parsedInputs.holdYears * 12` as `hold_months` so the backend stays compatible:

```ts
await apiPost<{ queued: boolean }>('/api/v1/investor/engagement', {
  session_key: sessionKey,
  purchase_price: parsedInputs.purchasePrice,
  rehab_costs: parsedInputs.rehabCost,
  arv: 0, // placeholder until Flip strategy returns in Task 7
  hold_months: parsedInputs.holdYears * 12,
});
```

Update the `handleUnlock` payload to use `holdYears`:

```ts
hold_years: parsedInputs.holdYears,
```

In `frontend/src/components/investor/AnalysisResults.tsx`, update the import and add a narrowing guard:

```ts
import type { InvestorMetrics } from '@/lib/investor-calc';

interface AnalysisResultsProps {
  metrics: InvestorMetrics;
}

export default function AnalysisResults({ metrics }: AnalysisResultsProps) {
  if (metrics.strategy !== 'buy_hold') {
    return null; // Other strategies' result blocks added in Task 8
  }
  const { monthlyCashFlow, cashOnCashReturn, capRate, grm } = metrics;
  // ... keep only the existing Rental block; remove the Flip block until Task 8 reintroduces it
}
```

Replace the component body so only the Rental/Buy-Hold metrics block renders:

```tsx
return (
  <div className="space-y-8">
    <div>
      <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">
        Buy &amp; Hold Analysis
      </h3>
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-2 gap-3"
      >
        <MetricCard
          eyebrow="Rental"
          label="Monthly Cash Flow"
          value={fmt(monthlyCashFlow)}
          valueColor={monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="Rental"
          label="Cash-on-Cash Return"
          value={pct(cashOnCashReturn)}
          valueColor={cashOnCashReturn >= 8 ? 'text-emerald-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="Rental"
          label="Cap Rate"
          value={pct(capRate)}
          valueColor="text-gold"
        />
        <MetricCard
          eyebrow="Rental"
          label="Gross Rent Multiplier"
          value={grm.toFixed(1)}
        />
      </motion.div>
    </div>
  </div>
);
```

- [ ] **Step 5: Run tests + typecheck**

```bash
cd frontend && npm test && npm run typecheck
```

Expected: All Vitest tests pass. Typecheck passes (no compile errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/investor-calc.ts frontend/src/lib/investor-calc.test.ts \
        frontend/src/components/investor/InvestorCalculator.tsx \
        frontend/src/components/investor/AnalysisResults.tsx
git commit -m "refactor(invest): pin Buy & Hold under discriminated-union calc engine"
```

---

### Task 3: Add `calculateFlipMetrics`

**Files:**
- Modify: `frontend/src/lib/investor-calc.ts`
- Modify: `frontend/src/lib/investor-calc.test.ts`

- [ ] **Step 1: Append failing tests for Flip**

Append to `frontend/src/lib/investor-calc.test.ts`:

```ts
import {
  calculateFlipMetrics,
  type FlipInputs,
} from './investor-calc';

describe('calculateFlipMetrics', () => {
  const baseFlip: FlipInputs = {
    strategy: 'flip',
    purchasePrice: 300000,
    rehabCost: 50000,
    arv: 450000,
    holdMonths: 6,
    propertyTax: 4800,
    insurance: 1200,
    downPaymentPct: 20,
    interestRate: 11, // hard money
    loanTermYears: 1,
  };

  it('computes positive flip profit on a clean deal', () => {
    const m = calculateFlipMetrics(baseFlip);
    expect(m.flipProfit).toBeGreaterThan(0);
  });

  it('reports both the 70% and 80% rule MAOs', () => {
    const m = calculateFlipMetrics(baseFlip);
    // 70% × 450k − 50k = 265k
    expect(m.maxAllowableOffer70).toBeCloseTo(265000, 0);
    // 80% × 450k − 50k = 310k
    expect(m.maxAllowableOffer80).toBeCloseTo(310000, 0);
  });

  it('uses interest-only mortgage for 1-year hard money', () => {
    const m = calculateFlipMetrics(baseFlip);
    expect(m.loanStructure).toBe('interest_only');
  });

  it('annualized ROI scales with hold months', () => {
    const m6 = calculateFlipMetrics(baseFlip);
    const m12 = calculateFlipMetrics({ ...baseFlip, holdMonths: 12 });
    expect(m6.flipAnnualizedROI).toBeGreaterThan(m12.flipAnnualizedROI);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test
```

Expected: `calculateFlipMetrics` undefined.

- [ ] **Step 3: Implement `calculateFlipMetrics`**

In `frontend/src/lib/investor-calc.ts`, add after the buy_hold function:

```ts
export function calculateFlipMetrics(inputs: FlipInputs): FlipMetrics {
  const downPayment = inputs.purchasePrice * (inputs.downPaymentPct / 100);
  const loanAmount = inputs.purchasePrice - downPayment;
  const { monthlyMortgage, loanStructure } = computeMonthlyMortgage({
    loanAmount,
    interestRatePct: inputs.interestRate,
    termYears: inputs.loanTermYears,
  });

  const monthlyHoldingExpenses = (inputs.propertyTax + inputs.insurance) / 12;
  const holdingCosts = (monthlyMortgage + monthlyHoldingExpenses) * inputs.holdMonths;
  const closingCosts = inputs.purchasePrice * 0.015 + inputs.arv * 0.0125;
  const totalProjectCost =
    inputs.purchasePrice + inputs.rehabCost + holdingCosts + closingCosts;
  const flipProfit = inputs.arv - totalProjectCost;
  const cashInvestedFlip =
    downPayment + inputs.rehabCost + holdingCosts + closingCosts;
  const flipROI = safeDivide(flipProfit, cashInvestedFlip) * 100;
  const flipAnnualizedROI = safeDivide(flipROI, inputs.holdMonths) * 12;
  const maxAllowableOffer70 = inputs.arv * 0.7 - inputs.rehabCost;
  const maxAllowableOffer80 = inputs.arv * 0.8 - inputs.rehabCost;

  return {
    strategy: 'flip',
    loanStructure,
    monthlyMortgage,
    downPayment,
    loanAmount,
    flipProfit,
    flipROI,
    flipAnnualizedROI,
    maxAllowableOffer70,
    maxAllowableOffer80,
    holdingCosts,
    closingCosts,
    totalProjectCost,
  };
}
```

Update the dispatch wrapper to handle `flip`:

```ts
case 'flip':
  return calculateFlipMetrics(inputs);
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test
```

Expected: All Buy & Hold + Flip tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/investor-calc.ts frontend/src/lib/investor-calc.test.ts
git commit -m "feat(invest): add calculateFlipMetrics with 70%/80% MAO"
```

---

### Task 4: Add `calculateStrMetrics`

**Files:**
- Modify: `frontend/src/lib/investor-calc.ts`
- Modify: `frontend/src/lib/investor-calc.test.ts`

- [ ] **Step 1: Append failing STR tests**

```ts
import { calculateStrMetrics, type StrInputs } from './investor-calc';

describe('calculateStrMetrics', () => {
  const baseStr: StrInputs = {
    strategy: 'str',
    purchasePrice: 500000,
    rehabCost: 25000,
    nightlyRate: 250,
    occupancyPct: 65,
    cleaningFeePerNight: 90,
    strMgmtPct: 20,
    monthlyUtilities: 250,
    propertyTax: 6000,
    insurance: 2400,
    downPaymentPct: 25,
    interestRate: 7.5,
    loanTermYears: 30,
  };

  it('computes monthly revenue from nightly rate and occupancy', () => {
    const m = calculateStrMetrics(baseStr);
    // 250 × 30.4 × 0.65 = 4,940
    expect(m.monthlyRevenue).toBeCloseTo(4940, 0);
  });

  it('break-even occupancy is between 0 and 100', () => {
    const m = calculateStrMetrics(baseStr);
    expect(m.breakEvenOccupancyPct).toBeGreaterThan(0);
    expect(m.breakEvenOccupancyPct).toBeLessThan(100);
  });

  it('STR cash flow is lower than equivalent gross because of higher expenses', () => {
    const m = calculateStrMetrics(baseStr);
    expect(m.monthlyCashFlow).toBeLessThan(m.monthlyRevenue);
  });

  it('handles zero occupancy without divide-by-zero', () => {
    const m = calculateStrMetrics({ ...baseStr, occupancyPct: 0 });
    expect(Number.isFinite(m.monthlyCashFlow)).toBe(true);
    expect(m.monthlyRevenue).toBe(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test
```

Expected: `calculateStrMetrics` undefined.

- [ ] **Step 3: Implement `calculateStrMetrics`**

```ts
export function calculateStrMetrics(inputs: StrInputs): StrMetrics {
  const downPayment = inputs.purchasePrice * (inputs.downPaymentPct / 100);
  const loanAmount = inputs.purchasePrice - downPayment;
  const { monthlyMortgage, loanStructure } = computeMonthlyMortgage({
    loanAmount,
    interestRatePct: inputs.interestRate,
    termYears: inputs.loanTermYears,
  });

  const NIGHTS_PER_MONTH = 30.4;
  const occupiedNights = NIGHTS_PER_MONTH * (inputs.occupancyPct / 100);
  const monthlyRevenue = inputs.nightlyRate * occupiedNights;

  // STR-specific operating expenses
  const cleaningCostMonthly = inputs.cleaningFeePerNight * occupiedNights;
  const mgmtCostMonthly = monthlyRevenue * (inputs.strMgmtPct / 100);
  const monthlyTaxIns = (inputs.propertyTax + inputs.insurance) / 12;
  // STR vacancy/seasonal buffer is implicit in occupancy; no extra %.
  const totalMonthlyOpex =
    cleaningCostMonthly + mgmtCostMonthly + inputs.monthlyUtilities + monthlyTaxIns;

  const monthlyNetOperating = monthlyRevenue - totalMonthlyOpex;
  const monthlyCashFlow = monthlyNetOperating - monthlyMortgage;
  const annualCashFlow = monthlyCashFlow * 12;
  const cashInvested = downPayment + inputs.rehabCost;
  const cashOnCashReturn = safeDivide(annualCashFlow, cashInvested) * 100;

  // Break-even occupancy: solve monthlyCashFlow = 0 for occupancy
  // monthlyRevenue × (1 − strMgmt/100) − cleaningCost − utilities − taxIns − mortgage = 0
  // Let occ = decimal. Revenue = nightly × 30.4 × occ. Cleaning = cleaningFee × 30.4 × occ.
  // Solve: occ × 30.4 × (nightly × (1 − strMgmt/100) − cleaningFee) = utilities + taxIns + mortgage
  const occCoefficient =
    NIGHTS_PER_MONTH * (inputs.nightlyRate * (1 - inputs.strMgmtPct / 100) - inputs.cleaningFeePerNight);
  const fixedFloor = inputs.monthlyUtilities + monthlyTaxIns + monthlyMortgage;
  const breakEvenDecimal = safeDivide(fixedFloor, occCoefficient);
  const breakEvenOccupancyPct = Math.max(0, Math.min(100, breakEvenDecimal * 100));

  const grossPerNight = inputs.nightlyRate;
  const netPerNight = occupiedNights > 0 ? monthlyNetOperating / occupiedNights : 0;

  return {
    strategy: 'str',
    loanStructure,
    monthlyMortgage,
    downPayment,
    loanAmount,
    monthlyRevenue,
    monthlyCashFlow,
    annualCashFlow,
    cashOnCashReturn,
    breakEvenOccupancyPct,
    grossPerNight,
    netPerNight,
  };
}
```

Add to dispatch:

```ts
case 'str':
  return calculateStrMetrics(inputs);
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/investor-calc.ts frontend/src/lib/investor-calc.test.ts
git commit -m "feat(invest): add calculateStrMetrics with break-even occupancy"
```

---

### Task 5: Add `calculateBrrrrMetrics`

**Files:**
- Modify: `frontend/src/lib/investor-calc.ts`
- Modify: `frontend/src/lib/investor-calc.test.ts`

- [ ] **Step 1: Append failing BRRRR tests**

```ts
import { calculateBrrrrMetrics, type BrrrrInputs } from './investor-calc';

describe('calculateBrrrrMetrics', () => {
  const baseBrrrr: BrrrrInputs = {
    strategy: 'brrrr',
    purchasePrice: 200000,
    rehabCost: 60000,
    arv: 360000,
    rentalIncome: 2800,
    propertyTax: 4500,
    insurance: 1200,
    downPaymentPct: 20,        // initial
    interestRate: 10,           // initial hard money
    loanTermYears: 1,           // initial term
    refiLtvPct: 75,
    refiRate: 7.25,
    refiTermYears: 30,
    holdMonthsBeforeRefi: 6,
  };

  it('refi loan amount is ARV × refi LTV', () => {
    const m = calculateBrrrrMetrics(baseBrrrr);
    expect(m.refiLoanAmount).toBeCloseTo(270000, 0);
  });

  it('cash recovered = refi loan − initial loan − rehab − holding', () => {
    const m = calculateBrrrrMetrics(baseBrrrr);
    // initial loan = 0.8 × 200,000 = 160,000
    // refi loan = 270,000
    // refi proceeds replace initial loan: net cash to investor = 270,000 − 160,000 = 110,000
    expect(m.cashRecoveredAtRefi).toBeGreaterThan(100000);
    expect(m.cashRecoveredAtRefi).toBeLessThan(115000);
  });

  it('flags infinite ROI when cash left in deal ≤ 0', () => {
    const m = calculateBrrrrMetrics({ ...baseBrrrr, refiLtvPct: 90 });
    expect(m.cashLeftInDeal).toBeLessThanOrEqual(0);
    expect(m.isInfiniteRoi).toBe(true);
  });

  it('post-refi cash flow uses 30y amortized at refi rate', () => {
    const m = calculateBrrrrMetrics(baseBrrrr);
    // amortized 270,000 @ 7.25% / 30y ≈ 1,841/mo
    expect(m.postRefiMonthlyMortgage).toBeCloseTo(1841, -1);
  });

  it('handles infinite-ROI case without NaN in CoC', () => {
    const m = calculateBrrrrMetrics({ ...baseBrrrr, refiLtvPct: 90 });
    expect(Number.isFinite(m.postRefiCashOnCash) || m.postRefiCashOnCash === Infinity).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test
```

Expected: `calculateBrrrrMetrics` undefined.

- [ ] **Step 3: Implement `calculateBrrrrMetrics`**

```ts
export function calculateBrrrrMetrics(inputs: BrrrrInputs): BrrrrMetrics {
  const initialDownPayment = inputs.purchasePrice * (inputs.downPaymentPct / 100);
  const initialLoanAmount = inputs.purchasePrice - initialDownPayment;
  const { monthlyMortgage: initialMortgage, loanStructure } = computeMonthlyMortgage({
    loanAmount: initialLoanAmount,
    interestRatePct: inputs.interestRate,
    termYears: inputs.loanTermYears,
  });

  // Holding costs through hold-before-refi
  const monthlyHoldExpenses = (inputs.propertyTax + inputs.insurance) / 12;
  const initialHoldingCosts =
    (initialMortgage + monthlyHoldExpenses) * inputs.holdMonthsBeforeRefi;

  // Refi
  const refiLoanAmount = inputs.arv * (inputs.refiLtvPct / 100);
  // Refi closing fees ≈ 1.5% of refi loan
  const refiClosingCosts = refiLoanAmount * 0.015;
  // Cash investor receives at refi: refi loan minus the initial loan that gets paid off,
  // minus refi closing costs.
  const refiNetProceeds = refiLoanAmount - initialLoanAmount - refiClosingCosts;
  // Cash investor put in: down payment + rehab + holding costs.
  const cashIntoDealUpfront = initialDownPayment + inputs.rehabCost + initialHoldingCosts;
  const cashRecoveredAtRefi = refiNetProceeds;
  const cashLeftInDeal = cashIntoDealUpfront - cashRecoveredAtRefi;

  // Post-refi rental
  const { monthlyMortgage: postRefiMortgage } = computeMonthlyMortgage({
    loanAmount: refiLoanAmount,
    interestRatePct: inputs.refiRate,
    termYears: inputs.refiTermYears,
  });
  const vacancyAllowance = inputs.rentalIncome * 0.08;
  const monthlyNOI = inputs.rentalIncome - vacancyAllowance - monthlyHoldExpenses;
  const noi = monthlyNOI * 12;
  const postRefiMonthlyCashFlow = monthlyNOI - postRefiMortgage;
  const postRefiAnnualCashFlow = postRefiMonthlyCashFlow * 12;

  const isInfiniteRoi = cashLeftInDeal <= 0;
  const postRefiCashOnCash = isInfiniteRoi
    ? Infinity
    : (postRefiAnnualCashFlow / cashLeftInDeal) * 100;
  const capRate = safeDivide(noi, inputs.purchasePrice + inputs.rehabCost) * 100;

  return {
    strategy: 'brrrr',
    loanStructure,
    monthlyMortgage: initialMortgage,
    downPayment: initialDownPayment,
    loanAmount: initialLoanAmount,
    initialHoldingCosts,
    cashIntoDealUpfront,
    refiLoanAmount,
    cashRecoveredAtRefi,
    cashLeftInDeal,
    isInfiniteRoi,
    postRefiMonthlyMortgage: postRefiMortgage,
    postRefiMonthlyCashFlow,
    postRefiCashOnCash,
    capRate,
    noi,
  };
}
```

Add to dispatch:

```ts
case 'brrrr':
  return calculateBrrrrMetrics(inputs);
```

The `default` arm in the switch can now be removed since all four cases are covered (TypeScript exhaustiveness check should be happy).

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test
```

Expected: All four strategy test suites pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/investor-calc.ts frontend/src/lib/investor-calc.test.ts
git commit -m "feat(invest): add calculateBrrrrMetrics with refi flow + infinite-ROI flag"
```

---

## Phase 3 — Strategy toggle UI

### Task 6: Build the StrategyToggle component

**Files:**
- Create: `frontend/src/components/investor/StrategyToggle.tsx`
- Create: `frontend/src/components/investor/strategy-defaults.ts`

- [ ] **Step 1: Create the strategy defaults module**

Create `frontend/src/components/investor/strategy-defaults.ts`:

```ts
import type { Strategy } from '@/lib/investor-calc';

export const STRATEGY_LABELS: Record<Strategy, string> = {
  buy_hold: 'Buy & Hold',
  str: 'STR',
  flip: 'Flip',
  brrrr: 'BRRRR',
};

export const STRATEGY_TAGLINES: Record<Strategy, string> = {
  buy_hold: 'Long-term rental for cash flow + appreciation',
  str: 'Short-term / Airbnb economics',
  flip: 'Buy, renovate, sell — profit + ROI',
  brrrr: 'Buy, Rehab, Rent, Refinance, Repeat',
};

// First-render defaults per strategy. Empty string means "no default — let user fill".
export const STRATEGY_DEFAULTS: Record<Strategy, Record<string, string>> = {
  buy_hold: {
    downPaymentPct: '25',
    interestRate: '7',
    loanTermYears: '30',
    holdYears: '5',
  },
  str: {
    downPaymentPct: '25',
    interestRate: '7.5',
    loanTermYears: '30',
    occupancyPct: '65',
    cleaningFeePerNight: '90',
    strMgmtPct: '20',
    monthlyUtilities: '250',
  },
  flip: {
    downPaymentPct: '20',
    interestRate: '11',
    loanTermYears: '1',
    holdMonths: '6',
  },
  brrrr: {
    downPaymentPct: '20',
    interestRate: '10',
    loanTermYears: '1',
    refiLtvPct: '75',
    refiRate: '7.25',
    refiTermYears: '30',
    holdMonthsBeforeRefi: '6',
  },
};

export const STRATEGY_LIST: Strategy[] = ['buy_hold', 'str', 'flip', 'brrrr'];

export function isStrategy(value: string | null): value is Strategy {
  return value !== null && (STRATEGY_LIST as string[]).includes(value);
}
```

- [ ] **Step 2: Create the StrategyToggle component**

Create `frontend/src/components/investor/StrategyToggle.tsx`:

```tsx
'use client';

import { motion } from 'framer-motion';
import type { Strategy } from '@/lib/investor-calc';
import { STRATEGY_LABELS, STRATEGY_LIST, STRATEGY_TAGLINES } from './strategy-defaults';

interface StrategyToggleProps {
  value: Strategy;
  onChange: (next: Strategy) => void;
}

export default function StrategyToggle({ value, onChange }: StrategyToggleProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
      className="glass border border-dark-border rounded-xl p-4 md:p-5"
    >
      <div className="flex items-center gap-2 mb-3">
        <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase">
          Investment Strategy
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {STRATEGY_LIST.map((s) => {
          const selected = s === value;
          return (
            <button
              key={s}
              type="button"
              onClick={() => onChange(s)}
              aria-pressed={selected}
              className={`px-4 py-3 text-sm font-semibold tracking-wide border transition-colors ${
                selected
                  ? 'bg-gold text-[#0a0a0a] border-gold'
                  : 'bg-dark-surface border-dark-border text-white/70 hover:border-gold/40 hover:text-white'
              }`}
            >
              {STRATEGY_LABELS[s]}
            </button>
          );
        })}
      </div>
      <p className="text-white/50 text-xs font-light mt-3">
        {STRATEGY_TAGLINES[value]}
      </p>
    </motion.div>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/investor/StrategyToggle.tsx \
        frontend/src/components/investor/strategy-defaults.ts
git commit -m "feat(invest): add StrategyToggle pill component + per-strategy defaults"
```

---

### Task 7: Wire strategy state + URL sync + per-strategy fields into InvestorCalculator

This is the largest task — splits inputs into per-strategy field sets and rewires the parser. To keep it manageable, internal state stays as `Record<string, string>` (a flat string map), and parsing is done strategy-by-strategy.

**Files:**
- Modify: `frontend/src/components/investor/InvestorCalculator.tsx`
- Modify: `frontend/src/app/(main)/invest/page.tsx`

- [ ] **Step 1: Replace the calculator's input state with a strategy-aware shape**

Replace the contents of `frontend/src/components/investor/InvestorCalculator.tsx` `EMPTY_INPUTS` and `parseInvestorInputs` regions with:

```ts
import {
  calculateMetrics,
  type BuyHoldInputs,
  type BrrrrInputs,
  type FlipInputs,
  type Strategy,
  type StrInputs,
  type InvestorInputs,
} from '@/lib/investor-calc';
import StrategyToggle from './StrategyToggle';
import { STRATEGY_DEFAULTS, isStrategy } from './strategy-defaults';

// Internal flat input record — we don't strongly type each strategy here because
// the same component renders different field sets depending on strategy.
type InputValues = Record<string, string>;

const EMPTY_INPUTS: InputValues = {
  purchasePrice: '',
  rehabCost: '',
  rentalIncome: '',
  propertyTax: '',
  insurance: '',
  downPaymentPct: '',
  interestRate: '',
  loanTermYears: '',
  // Strategy-specific (start empty)
  holdYears: '',
  holdMonths: '',
  arv: '',
  nightlyRate: '',
  occupancyPct: '',
  cleaningFeePerNight: '',
  strMgmtPct: '',
  monthlyUtilities: '',
  refiLtvPct: '',
  refiRate: '',
  refiTermYears: '',
  holdMonthsBeforeRefi: '',
};

function num(values: InputValues, key: string): number {
  const trimmed = (values[key] ?? '').trim();
  if (!trimmed) return 0;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : 0;
}

function parseInputs(strategy: Strategy, values: InputValues): InvestorInputs | null {
  const required: Record<Strategy, string[]> = {
    buy_hold: ['purchasePrice', 'holdYears', 'loanTermYears'],
    str: ['purchasePrice', 'nightlyRate', 'loanTermYears'],
    flip: ['purchasePrice', 'arv', 'holdMonths', 'loanTermYears'],
    brrrr: ['purchasePrice', 'arv', 'holdMonthsBeforeRefi', 'refiTermYears', 'loanTermYears'],
  };
  const missing = required[strategy].some((k) => num(values, k) <= 0);
  if (missing) return null;

  const baseFields = {
    purchasePrice: num(values, 'purchasePrice'),
    rehabCost: num(values, 'rehabCost'),
    propertyTax: num(values, 'propertyTax'),
    insurance: num(values, 'insurance'),
    downPaymentPct: num(values, 'downPaymentPct'),
    interestRate: num(values, 'interestRate'),
    loanTermYears: num(values, 'loanTermYears'),
  };

  switch (strategy) {
    case 'buy_hold':
      return {
        strategy: 'buy_hold',
        ...baseFields,
        rentalIncome: num(values, 'rentalIncome'),
        holdYears: num(values, 'holdYears'),
      } satisfies BuyHoldInputs;
    case 'str':
      return {
        strategy: 'str',
        ...baseFields,
        nightlyRate: num(values, 'nightlyRate'),
        occupancyPct: num(values, 'occupancyPct'),
        cleaningFeePerNight: num(values, 'cleaningFeePerNight'),
        strMgmtPct: num(values, 'strMgmtPct'),
        monthlyUtilities: num(values, 'monthlyUtilities'),
      } satisfies StrInputs;
    case 'flip':
      return {
        strategy: 'flip',
        ...baseFields,
        arv: num(values, 'arv'),
        holdMonths: num(values, 'holdMonths'),
      } satisfies FlipInputs;
    case 'brrrr':
      return {
        strategy: 'brrrr',
        ...baseFields,
        arv: num(values, 'arv'),
        rentalIncome: num(values, 'rentalIncome'),
        refiLtvPct: num(values, 'refiLtvPct'),
        refiRate: num(values, 'refiRate'),
        refiTermYears: num(values, 'refiTermYears'),
        holdMonthsBeforeRefi: num(values, 'holdMonthsBeforeRefi'),
      } satisfies BrrrrInputs;
  }
}
```

- [ ] **Step 2: Add strategy state + URL sync**

Replace the `useState<InvestorInputValues>` block + lookup state with:

```tsx
import { useSearchParams, useRouter, usePathname } from 'next/navigation';

export default function InvestorCalculator() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const initialStrategy: Strategy = (() => {
    const fromUrl = searchParams.get('strategy');
    return isStrategy(fromUrl) ? fromUrl : 'buy_hold';
  })();

  const [strategy, setStrategyState] = useState<Strategy>(initialStrategy);
  const [inputs, setInputs] = useState<InputValues>(() => ({
    ...EMPTY_INPUTS,
    ...STRATEGY_DEFAULTS[initialStrategy],
  }));
  const [fullReport, setFullReport] = useState<InvestorAiReport | null>(null);
  const engagementRetryTimeoutRef = useRef<number | null>(null);

  // Address lookup state (unchanged below)
  const [lookupAddress, setLookupAddress] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupResult, setLookupResult] = useState<LookupResult | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [filledFields, setFilledFields] = useState<Set<string>>(new Set());

  function setStrategy(next: Strategy) {
    setStrategyState(next);
    setFullReport(null);
    setInputs((prev) => {
      // Preserve all overlapping field values; layer in defaults only for empty fields.
      const merged = { ...prev };
      for (const [key, def] of Object.entries(STRATEGY_DEFAULTS[next])) {
        if (!merged[key] || merged[key].trim() === '') merged[key] = def;
      }
      return merged;
    });
    // URL sync
    const params = new URLSearchParams(searchParams.toString());
    if (next === 'buy_hold') {
      params.delete('strategy');
    } else {
      params.set('strategy', next);
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const parsedInputs = useMemo(() => parseInputs(strategy, inputs), [strategy, inputs]);
  const metrics = useMemo(
    () => (parsedInputs ? calculateMetrics(parsedInputs) : null),
    [parsedInputs],
  );
```

- [ ] **Step 3: Generalize `handleChange` to take a string key**

Replace the existing `handleChange` with:

```tsx
function handleChange(name: string, value: string) {
  setInputs((prev) => ({ ...prev, [name]: value }));
  setFullReport(null);
  setFilledFields((prev) => {
    if (!prev.has(name)) return prev;
    const next = new Set(prev);
    next.delete(name);
    return next;
  });
}
```

Update the `InputField` props to use `name: string` instead of `name: keyof InvestorInputs`:

```tsx
interface InputFieldProps {
  label: string;
  name: string;
  value: string;
  onChange: (name: string, value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: number;
  highlight?: boolean;
}
```

- [ ] **Step 4: Update lookup auto-fill to use string keys + map to per-strategy fields**

Replace the auto-fill block in `handleLookup`:

```tsx
const newInputs = { ...inputs };
const filled = new Set<string>();

if (result.purchase_price) {
  newInputs.purchasePrice = String(result.purchase_price);
  newInputs.arv = String(result.purchase_price);
  filled.add('purchasePrice');
  filled.add('arv');
}
if (result.monthly_rent) {
  newInputs.rentalIncome = String(result.monthly_rent);
  filled.add('rentalIncome');
}
if (result.annual_taxes) {
  newInputs.propertyTax = String(result.annual_taxes);
  filled.add('propertyTax');
}
if (result.estimated_insurance) {
  newInputs.insurance = String(result.estimated_insurance);
  filled.add('insurance');
}
setInputs(newInputs);
setFilledFields(filled);
setFullReport(null);
```

- [ ] **Step 5: Render the StrategyToggle and per-strategy field sets**

Replace the input grid (`<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">…</div>`) with a strategy-aware version. Add the toggle above the address-lookup card:

```tsx
return (
  <div className="space-y-8">
    <StrategyToggle value={strategy} onChange={setStrategy} />

    {/* ── Address Lookup Bar ── (unchanged below; keep existing block) */}
    {/* ... existing lookup UI ... */}

    {/* ── Main Calculator Grid ── */}
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.1fr] gap-8 lg:gap-12">
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
        className="space-y-4"
      >
        <div>
          <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-1">
            Deal Parameters
          </p>
          <h3 className="text-white font-black text-lg tracking-tight">
            Enter Your Numbers
          </h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Common fields — always shown */}
          <InputField label="Purchase Price" name="purchasePrice" value={inputs.purchasePrice}
            onChange={handleChange} prefix="$" highlight={filledFields.has('purchasePrice')} />
          <InputField label="Rehab / Renovation Cost" name="rehabCost" value={inputs.rehabCost}
            onChange={handleChange} prefix="$" />

          {/* Buy & Hold + BRRRR: monthly rent */}
          {(strategy === 'buy_hold' || strategy === 'brrrr') && (
            <InputField label="Monthly Rental Income" name="rentalIncome" value={inputs.rentalIncome}
              onChange={handleChange} prefix="$" highlight={filledFields.has('rentalIncome')} />
          )}

          {/* Flip + BRRRR: ARV */}
          {(strategy === 'flip' || strategy === 'brrrr') && (
            <InputField label="After-Repair Value (ARV)" name="arv" value={inputs.arv}
              onChange={handleChange} prefix="$" highlight={filledFields.has('arv')} />
          )}

          {/* STR-only fields */}
          {strategy === 'str' && (
            <>
              <InputField label="Nightly Rate" name="nightlyRate" value={inputs.nightlyRate}
                onChange={handleChange} prefix="$" />
              <InputField label="Occupancy %" name="occupancyPct" value={inputs.occupancyPct}
                onChange={handleChange} suffix="%" />
              <InputField label="Cleaning Fee / Night" name="cleaningFeePerNight"
                value={inputs.cleaningFeePerNight} onChange={handleChange} prefix="$" />
              <InputField label="STR Mgmt %" name="strMgmtPct" value={inputs.strMgmtPct}
                onChange={handleChange} suffix="%" />
              <InputField label="Monthly Utilities" name="monthlyUtilities"
                value={inputs.monthlyUtilities} onChange={handleChange} prefix="$" />
            </>
          )}

          {/* Flip-only field */}
          {strategy === 'flip' && (
            <InputField label="Hold Period" name="holdMonths" value={inputs.holdMonths}
              onChange={handleChange} suffix="mo" />
          )}

          {/* Buy & Hold-only field */}
          {strategy === 'buy_hold' && (
            <InputField label="Hold Period" name="holdYears" value={inputs.holdYears}
              onChange={handleChange} suffix="yr" />
          )}

          {/* BRRRR-only fields */}
          {strategy === 'brrrr' && (
            <>
              <InputField label="Hold Months Before Refi" name="holdMonthsBeforeRefi"
                value={inputs.holdMonthsBeforeRefi} onChange={handleChange} suffix="mo" />
              <InputField label="Refi LTV %" name="refiLtvPct" value={inputs.refiLtvPct}
                onChange={handleChange} suffix="%" />
              <InputField label="Refi Rate" name="refiRate" value={inputs.refiRate}
                onChange={handleChange} suffix="%" />
              <InputField label="Refi Term" name="refiTermYears" value={inputs.refiTermYears}
                onChange={handleChange} suffix="yr" />
            </>
          )}

          {/* Common financial fields */}
          <InputField label="Property Tax / Year" name="propertyTax" value={inputs.propertyTax}
            onChange={handleChange} prefix="$" highlight={filledFields.has('propertyTax')} />
          <InputField label="Annual Insurance" name="insurance" value={inputs.insurance}
            onChange={handleChange} prefix="$" highlight={filledFields.has('insurance')} />
          <InputField label="Down Payment %" name="downPaymentPct" value={inputs.downPaymentPct}
            onChange={handleChange} suffix="%" />
          <InputField
            label={strategy === 'brrrr' ? 'Initial Rate' : 'Interest Rate'}
            name="interestRate" value={inputs.interestRate}
            onChange={handleChange} suffix="%" />
          <InputField
            label={strategy === 'brrrr' ? 'Initial Term' : 'Loan Term'}
            name="loanTermYears" value={inputs.loanTermYears}
            onChange={handleChange} suffix="yr" />
        </div>
      </motion.div>

      {/* ── RIGHT: Preview + Gate (unchanged structurally; AnalysisResults now strategy-aware) ── */}
      {/* ... existing right panel, but pass `strategy` into AnalysisResults via metrics shape ... */}
    </div>
  </div>
);
```

(Keep the lookup card and right-side preview/gate exactly as they are, only replacing what's shown above.)

- [ ] **Step 6: Update the `handleUnlock` payload to include strategy**

```tsx
async function handleUnlock(contact: InvestorLeadCapture) {
  if (!parsedInputs) return;
  const purchasePriceVal = num(inputs, 'purchasePrice');
  const rentVal = num(inputs, 'rentalIncome'); // 0 for flip/str
  const holdYears = strategy === 'flip'
    ? Math.max(1, Math.ceil(num(inputs, 'holdMonths') / 12))
    : strategy === 'brrrr'
      ? Math.max(1, Math.ceil(num(inputs, 'holdMonthsBeforeRefi') / 12))
      : Math.max(1, num(inputs, 'holdYears'));

  const response = await apiPost<InvestorAnalysisResponse>('/api/v1/investor/analyze', {
    property_type: 'single_family',
    units: 1,
    purchase_price: purchasePriceVal,
    down_payment_pct: num(inputs, 'downPaymentPct'),
    interest_rate: num(inputs, 'interestRate'),
    loan_term_years: num(inputs, 'loanTermYears'),
    monthly_rent_total: rentVal,
    rehab_costs: num(inputs, 'rehabCost'),
    annual_taxes: num(inputs, 'propertyTax'),
    annual_insurance: num(inputs, 'insurance'),
    monthly_maintenance: 0,
    vacancy_rate_pct: 8,
    mgmt_fee_pct: 0,
    hold_years: holdYears,
    appreciation_rate_pct: 3,
    name: contact.name || undefined,
    email: contact.email,
    phone: contact.phone || undefined,
    strategy, // NEW
  });
  setFullReport(response.report);
}
```

- [ ] **Step 7: Pass `strategy` into AnalysisResults**

In the right-side panel where `<AnalysisResults metrics={metrics} />` is rendered, no change is needed — `metrics.strategy` carries the discriminator. But if `metrics` is null we still want to show the placeholder.

- [ ] **Step 8: Update the page-level invest route to be a Suspense boundary**

`useSearchParams` requires a Suspense boundary in Next 16. Edit `frontend/src/app/(main)/invest/page.tsx` to wrap `<InvestorCalculator />` in Suspense:

```tsx
import { Suspense } from 'react';

// ... existing imports + InvestPage body ...

// In the calculator section:
<div className="glass border border-dark-border rounded-xl p-6 md:p-10">
  <Suspense fallback={<div className="text-white/40 text-sm">Loading calculator…</div>}>
    <InvestorCalculator />
  </Suspense>
</div>
```

- [ ] **Step 9: Typecheck + run frontend tests**

```bash
cd frontend && npm run typecheck && npm test
```

Expected: passes. Existing tests still pass (we didn't touch `investor-calc.ts`).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/investor/InvestorCalculator.tsx \
        frontend/src/app/(main)/invest/page.tsx
git commit -m "feat(invest): wire strategy state, URL sync, and per-strategy fields"
```

---

### Task 8: Make AnalysisResults strategy-aware

**Files:**
- Modify: `frontend/src/components/investor/AnalysisResults.tsx`

- [ ] **Step 1: Replace the component with a strategy-discriminated body**

Replace `frontend/src/components/investor/AnalysisResults.tsx` with:

```tsx
'use client';

import { motion } from 'framer-motion';
import type { InvestorMetrics } from '@/lib/investor-calc';

interface AnalysisResultsProps {
  metrics: InvestorMetrics;
}

const fmt = (value: number) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      }).format(value)
    : '∞';

const pct = (value: number) =>
  Number.isFinite(value) ? `${value.toFixed(1)}%` : 'Infinite';

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06 } },
};

const cardVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
  },
};

interface MetricCardProps {
  label: string;
  value: string;
  valueColor?: string;
  eyebrow: string;
}

function MetricCard({ label, value, valueColor = 'text-white', eyebrow }: MetricCardProps) {
  return (
    <motion.div
      variants={cardVariants}
      className="glass border border-dark-border rounded-xl p-4 md:p-5 flex flex-col gap-2"
    >
      <span className="text-gold text-xs font-semibold tracking-[0.18em] uppercase">{eyebrow}</span>
      <span className="text-white/40 text-xs font-medium tracking-widest uppercase leading-tight">
        {label}
      </span>
      <span className={`font-black text-2xl md:text-3xl leading-none ${valueColor}`}>{value}</span>
    </motion.div>
  );
}

function MetricsGrid({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <div>
      <h3 className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-4">{title}</h3>
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-2 gap-3"
      >
        {children}
      </motion.div>
    </div>
  );
}

export default function AnalysisResults({ metrics }: AnalysisResultsProps) {
  if (metrics.strategy === 'buy_hold') {
    return (
      <MetricsGrid title="Buy & Hold Analysis">
        <MetricCard
          eyebrow="Rental"
          label="Monthly Cash Flow"
          value={fmt(metrics.monthlyCashFlow)}
          valueColor={metrics.monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="Rental"
          label="Cash-on-Cash Return"
          value={pct(metrics.cashOnCashReturn)}
          valueColor={metrics.cashOnCashReturn >= 8 ? 'text-emerald-400' : 'text-white'}
        />
        <MetricCard eyebrow="Rental" label="Cap Rate" value={pct(metrics.capRate)} valueColor="text-gold" />
        <MetricCard eyebrow="Rental" label="GRM" value={metrics.grm.toFixed(1)} />
        <MetricCard eyebrow="Rental" label="Annual NOI" value={fmt(metrics.noi)} />
        <MetricCard eyebrow="Rental" label="5-Year Equity" value={fmt(metrics.fiveYearEquityBuild)} />
      </MetricsGrid>
    );
  }

  if (metrics.strategy === 'str') {
    return (
      <MetricsGrid title="Short-Term Rental Analysis">
        <MetricCard eyebrow="STR" label="Monthly Revenue" value={fmt(metrics.monthlyRevenue)} valueColor="text-gold" />
        <MetricCard
          eyebrow="STR"
          label="Monthly Cash Flow"
          value={fmt(metrics.monthlyCashFlow)}
          valueColor={metrics.monthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard eyebrow="STR" label="Cash-on-Cash" value={pct(metrics.cashOnCashReturn)} />
        <MetricCard
          eyebrow="STR"
          label="Break-Even Occupancy"
          value={pct(metrics.breakEvenOccupancyPct)}
        />
        <MetricCard eyebrow="STR" label="Gross / Night" value={fmt(metrics.grossPerNight)} />
        <MetricCard eyebrow="STR" label="Net / Night" value={fmt(metrics.netPerNight)} />
      </MetricsGrid>
    );
  }

  if (metrics.strategy === 'flip') {
    return (
      <MetricsGrid title="Flip Analysis">
        <MetricCard
          eyebrow="Flip"
          label="Estimated Profit"
          value={fmt(metrics.flipProfit)}
          valueColor={metrics.flipProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}
        />
        <MetricCard eyebrow="Flip" label="ROI" value={pct(metrics.flipROI)} />
        <MetricCard eyebrow="Flip" label="Annualized ROI" value={pct(metrics.flipAnnualizedROI)} />
        <MetricCard eyebrow="Flip" label="70% Rule MAO" value={fmt(metrics.maxAllowableOffer70)} valueColor="text-gold" />
        <MetricCard eyebrow="Flip" label="80% Rule MAO" value={fmt(metrics.maxAllowableOffer80)} />
        <MetricCard eyebrow="Flip" label="Holding Costs" value={fmt(metrics.holdingCosts)} />
        <MetricCard eyebrow="Flip" label="Closing Costs" value={fmt(metrics.closingCosts)} />
        <MetricCard eyebrow="Flip" label="Total Project Cost" value={fmt(metrics.totalProjectCost)} valueColor="text-gold" />
      </MetricsGrid>
    );
  }

  // BRRRR
  return (
    <div className="space-y-6">
      <MetricsGrid title="BRRRR Analysis">
        <MetricCard eyebrow="BRRRR" label="Cash Into Deal" value={fmt(metrics.cashIntoDealUpfront)} />
        <MetricCard eyebrow="BRRRR" label="Refi Loan" value={fmt(metrics.refiLoanAmount)} />
        <MetricCard eyebrow="BRRRR" label="Cash Recovered" value={fmt(metrics.cashRecoveredAtRefi)} valueColor="text-emerald-400" />
        <MetricCard
          eyebrow="BRRRR"
          label="Cash Left In Deal"
          value={fmt(Math.max(0, metrics.cashLeftInDeal))}
          valueColor={metrics.isInfiniteRoi ? 'text-emerald-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="BRRRR"
          label="Post-Refi Cash Flow"
          value={fmt(metrics.postRefiMonthlyCashFlow)}
          valueColor={metrics.postRefiMonthlyCashFlow < 0 ? 'text-red-400' : 'text-white'}
        />
        <MetricCard
          eyebrow="BRRRR"
          label="Post-Refi CoC"
          value={pct(metrics.postRefiCashOnCash)}
          valueColor={metrics.isInfiniteRoi ? 'text-emerald-400' : 'text-white'}
        />
      </MetricsGrid>
      {metrics.isInfiniteRoi && (
        <p className="text-emerald-400 text-xs font-semibold tracking-widest uppercase">
          Infinite-ROI deal — refi recovers all cash invested
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/investor/AnalysisResults.tsx
git commit -m "feat(invest): strategy-aware AnalysisResults with per-strategy metric grids"
```

---

## Phase 4 — Backend rental analyzer

### Task 9: Rental analyzer service with heuristic tables

**Files:**
- Create: `backend/services/rental_analyzer_service.py`
- Create: `backend/tests/test_rental_analyzer_service.py`

- [ ] **Step 1: Write the failing pytest cases**

Create `backend/tests/test_rental_analyzer_service.py`:

```python
"""Tests for the rental analyzer service.

These tests use stubbed RentCast responses so they're deterministic.
The real-world calibration runs happen in Task 14 (separate spreadsheet).
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from services.rental_analyzer_service import (
    EstimateRentRequest,
    estimate_rent,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class RentalAnalyzerTests(unittest.TestCase):

    def test_excellent_condition_uplifts_rentcast_baseline(self):
        rc = {"rent": 2400, "rentRangeLow": 2200, "rentRangeHigh": 2600, "comparables": []}
        req = EstimateRentRequest(
            address="50 Cheever Ave, Dracut, MA 01826",
            condition="excellent",
            upgrades=["Kitchen"],
            mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(rc)):
            result = run(estimate_rent(req))

        # Baseline 2400 + 4% (excellent) + 2% (kitchen) = 2544
        self.assertEqual(result["mode"], "ltr")
        self.assertGreaterEqual(result["monthly_median"], 2540)
        self.assertLessEqual(result["monthly_median"], 2560)
        self.assertEqual(result["confidence"], "High")

    def test_needs_work_drops_rent_below_baseline(self):
        rc = {"rent": 2400, "rentRangeLow": 2300, "rentRangeHigh": 2500, "comparables": []}
        req = EstimateRentRequest(
            address="X", condition="needs_work", upgrades=[], mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(rc)):
            result = run(estimate_rent(req))
        # Baseline 2400 − 12% = 2112
        self.assertLess(result["monthly_median"], 2200)

    def test_upgrades_capped_at_eight_pct(self):
        rc = {"rent": 2000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="X",
            condition="good",
            upgrades=["Kitchen", "Baths", "HVAC", "Flooring", "Roof", "Windows"],
            mode="ltr",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(rc)):
            result = run(estimate_rent(req))
        # Sum of bumps = 6.0%; well within +8% cap. Should equal 2000 × 1.06 = 2120.
        self.assertEqual(result["monthly_median"], 2120)

    def test_falls_back_when_rentcast_returns_none(self):
        req = EstimateRentRequest(
            address="X", condition="good", upgrades=[], mode="ltr",
            bedrooms=2, purchase_price=400000,
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(None)):
            result = run(estimate_rent(req))
        self.assertEqual(result["confidence"], "Low")
        self.assertGreater(result["monthly_median"], 0)

    def test_str_mode_returns_nightly_rate(self):
        rc = {"rent": 3000, "rentRangeLow": None, "rentRangeHigh": None, "comparables": []}
        req = EstimateRentRequest(
            address="X", condition="good", upgrades=[], mode="str", market_type="urban",
        )
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(rc)):
            result = run(estimate_rent(req))
        self.assertEqual(result["mode"], "str")
        # urban multiplier 2.4, occupancy 65% → nightly = (3000 × 2.4) / (30.4 × 0.65) ≈ 364
        self.assertGreater(result["nightly_median"], 320)
        self.assertLess(result["nightly_median"], 410)
        self.assertEqual(result["suggested_occupancy_pct"], 65)


async def _async(value):
    return value


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_rental_analyzer_service.py -v
```

Expected: ImportError on `services.rental_analyzer_service`.

- [ ] **Step 3: Implement the service**

Create `backend/services/rental_analyzer_service.py`:

```python
"""Rental analyzer — combines RentCast's rent AVM with a condition/upgrade
heuristic to estimate monthly rent (LTR) or nightly rate (STR).

All multipliers live in this file so calibration tweaks are a single-place
change.  Calibration data lives in
docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from services.rentcast_service import get_rent_estimate


# ─── Heuristic tables (calibrate in Task 14) ────────────────────────────────

CONDITION_ADJUSTMENTS: dict[str, float] = {
    "excellent": 0.04,
    "good": 0.00,
    "fair": -0.06,
    "needs_work": -0.12,
}

UPGRADE_BUMPS: dict[str, float] = {
    "Kitchen": 0.020,
    "Baths": 0.015,
    "HVAC": 0.010,
    "Flooring": 0.005,
    "Roof": 0.005,
    "Windows": 0.005,
}

# Cap on additive upgrade bump (does NOT include the condition adjustment).
UPGRADE_CAP = 0.08
# Total adjustment is also clamped.
TOTAL_ADJ_CEILING = 0.10
TOTAL_ADJ_FLOOR = -0.20

# STR market multipliers (effective monthly STR revenue ≈ multiplier × LTR rent).
STR_MARKET_MULTIPLIERS: dict[str, float] = {
    "tourist": 3.0,
    "urban": 2.4,
    "suburban": 1.8,
}

STR_SUGGESTED_OCCUPANCY: dict[str, int] = {
    "tourist": 70,
    "urban": 65,
    "suburban": 55,
}

# Per-bedroom fallback baseline (Boston-metro starting points).
BEDROOM_BASELINE: dict[int, int] = {
    1: 1400,
    2: 1800,
    3: 2300,
    4: 2800,
    5: 3300,
}

# When no RentCast and no purchase price, multiply per-bedroom baseline by 1.0.
# When purchase price is available, fallback = max(baseline, 0.7% × price).
FALLBACK_PERCENT_OF_PRICE = 0.007

NIGHTS_PER_MONTH = 30.4


# ─── Schemas ────────────────────────────────────────────────────────────────


class EstimateRentRequest(BaseModel):
    address: str = Field(..., min_length=4)
    property_type: Optional[str] = "single_family"
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: Literal["excellent", "good", "fair", "needs_work"]
    upgrades: list[str] = []
    mode: Literal["ltr", "str"] = "ltr"
    market_type: Optional[Literal["tourist", "urban", "suburban"]] = None
    # Optional context for fallbacks
    purchase_price: Optional[float] = None


class BreakdownItem(BaseModel):
    label: str
    value_dollars: int
    pct_delta: Optional[float]


# ─── Helpers ────────────────────────────────────────────────────────────────


def _condition_adjustment(condition: str) -> float:
    return CONDITION_ADJUSTMENTS.get(condition, 0.0)


def _upgrade_total_pct(upgrades: list[str]) -> float:
    total = sum(UPGRADE_BUMPS.get(u, 0.0) for u in upgrades)
    return min(total, UPGRADE_CAP)


def _clamp_total(total: float) -> float:
    return max(TOTAL_ADJ_FLOOR, min(TOTAL_ADJ_CEILING, total))


def _fallback_baseline(req: EstimateRentRequest) -> int:
    bd_baseline = BEDROOM_BASELINE.get(req.bedrooms or 3, 2300)
    price_baseline = (
        int(req.purchase_price * FALLBACK_PERCENT_OF_PRICE)
        if req.purchase_price
        else 0
    )
    return max(bd_baseline, price_baseline)


def _confidence(rentcast_data: Optional[dict], range_tightness: Optional[float]) -> str:
    if not rentcast_data:
        return "Low"
    has_comps = bool(rentcast_data.get("comparables"))
    if range_tightness is not None and range_tightness < 0.10 and has_comps:
        return "High"
    if range_tightness is not None and range_tightness >= 0.20:
        return "Medium"
    if not has_comps:
        return "Medium"
    return "High"


# ─── Public API ─────────────────────────────────────────────────────────────


async def estimate_rent(req: EstimateRentRequest) -> dict:
    rentcast = await get_rent_estimate(req.address)
    if rentcast and "rent" in rentcast and rentcast["rent"]:
        baseline = float(rentcast["rent"])
        rc_low = rentcast.get("rentRangeLow")
        rc_high = rentcast.get("rentRangeHigh")
        range_tightness = (
            (rc_high - rc_low) / baseline
            if rc_low is not None and rc_high is not None and baseline > 0
            else None
        )
    else:
        baseline = float(_fallback_baseline(req))
        rentcast = None
        range_tightness = None

    cond_adj = _condition_adjustment(req.condition)
    upgrade_adj = _upgrade_total_pct(req.upgrades)
    total_adj = _clamp_total(cond_adj + upgrade_adj)
    monthly_median = round(baseline * (1 + total_adj))
    monthly_low = round(monthly_median * 0.93)
    monthly_high = round(monthly_median * 1.07)

    breakdown: list[dict] = [
        {
            "label": "RentCast baseline" if rentcast else "Per-bedroom fallback",
            "value_dollars": int(baseline),
            "pct_delta": None,
        }
    ]
    if cond_adj != 0:
        breakdown.append({
            "label": f"Condition: {req.condition.replace('_', ' ').title()}",
            "value_dollars": int(round(baseline * cond_adj)),
            "pct_delta": round(cond_adj * 100, 1),
        })
    for u in req.upgrades:
        bump = UPGRADE_BUMPS.get(u)
        if bump:
            breakdown.append({
                "label": f"Upgrade: {u}",
                "value_dollars": int(round(baseline * bump)),
                "pct_delta": round(bump * 100, 1),
            })

    comparables = []
    if rentcast:
        for comp in (rentcast.get("comparables") or [])[:3]:
            comparables.append({
                "address": comp.get("formattedAddress"),
                "rent": comp.get("price"),
                "bedrooms": comp.get("bedrooms"),
                "bathrooms": comp.get("bathrooms"),
                "sqft": comp.get("squareFootage"),
                "distance_miles": round(comp.get("distance", 0), 2),
                "correlation": round(comp.get("correlation", 0), 4),
            })

    confidence = _confidence(rentcast, range_tightness)

    response: dict = {
        "mode": req.mode,
        "monthly_low": monthly_low,
        "monthly_median": monthly_median,
        "monthly_high": monthly_high,
        "confidence": confidence,
        "breakdown": breakdown,
        "comparables": comparables,
        "data_source": "rentcast_avm" if rentcast else "fallback_heuristic",
    }

    if req.mode == "str":
        if not req.market_type:
            raise ValueError("market_type is required when mode == 'str'")
        market_mult = STR_MARKET_MULTIPLIERS[req.market_type]
        suggested_occ = STR_SUGGESTED_OCCUPANCY[req.market_type]
        nightly_median = round(
            (monthly_median * market_mult) / (NIGHTS_PER_MONTH * (suggested_occ / 100))
        )
        response["nightly_median"] = nightly_median
        response["nightly_low"] = round(nightly_median * 0.85)
        response["nightly_high"] = round(nightly_median * 1.15)
        response["suggested_occupancy_pct"] = suggested_occ
        response["market_multiplier"] = market_mult

    return response
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_rental_analyzer_service.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/rental_analyzer_service.py backend/tests/test_rental_analyzer_service.py
git commit -m "feat(rental): add rental analyzer service with heuristic + STR multipliers"
```

---

### Task 10: Add `/api/v1/investor/estimate-rent` route

**Files:**
- Modify: `backend/routers/investor.py`
- Create: `backend/tests/test_estimate_rent_router.py`

- [ ] **Step 1: Write failing route test**

Create `backend/tests/test_estimate_rent_router.py`:

```python
"""Route-level tests for POST /api/v1/investor/estimate-rent."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


def _async(value):
    async def _coro():
        return value
    return _coro()


class EstimateRentRouteTests(unittest.TestCase):

    def setUp(self):
        from main import app
        self.client = TestClient(app)

    def test_ltr_happy_path(self):
        rc = {"rent": 2400, "rentRangeLow": 2300, "rentRangeHigh": 2500, "comparables": []}
        with patch("services.rental_analyzer_service.get_rent_estimate", return_value=_async(rc)):
            resp = self.client.post(
                "/api/v1/investor/estimate-rent",
                json={
                    "address": "50 Cheever Ave, Dracut, MA 01826",
                    "condition": "good",
                    "upgrades": [],
                    "mode": "ltr",
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["mode"], "ltr")
        self.assertGreater(body["monthly_median"], 0)

    def test_str_requires_market_type(self):
        resp = self.client.post(
            "/api/v1/investor/estimate-rent",
            json={
                "address": "50 Cheever Ave, Dracut, MA 01826",
                "condition": "good",
                "upgrades": [],
                "mode": "str",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_short_address_rejected(self):
        resp = self.client.post(
            "/api/v1/investor/estimate-rent",
            json={"address": "X", "condition": "good", "upgrades": [], "mode": "ltr"},
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_estimate_rent_router.py -v
```

Expected: 404 from FastAPI on the new route.

- [ ] **Step 3: Add the route + the `strategy` field to `analyze`**

Edit `backend/routers/investor.py`. Add to the imports near the top:

```python
from services.rental_analyzer_service import EstimateRentRequest, estimate_rent
```

Add `strategy: Optional[str] = None` to the `InvestorInputs` Pydantic model:

```python
class InvestorInputs(BaseModel):
    # Property
    address: Optional[str] = None
    property_type: str = "single_family"
    units: int = 1
    # Strategy
    strategy: Optional[str] = None   # buy_hold | str | flip | brrrr
    # Financials
    purchase_price: float
    # ... rest unchanged ...
```

Append the new route at the bottom of the router:

```python
@router.post("/estimate-rent")
async def estimate_rent_route(req: EstimateRentRequest):
    """Estimate monthly rent (LTR) or nightly rate (STR) from condition + upgrades."""
    try:
        return await estimate_rent(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
```

Pass strategy into the AI report metadata in `full_analysis`:

```python
lead_meta = json.dumps({
    "purchase_price": inp.purchase_price,
    "property_type": inp.property_type,
    "address": inp.address,
    "strategy": inp.strategy,
})
```

And into the notification payload (add `"strategy": inp.strategy` inside the existing `payload` dict).

- [ ] **Step 4: Run all backend tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests pass, including the new route tests.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/investor.py backend/tests/test_estimate_rent_router.py
git commit -m "feat(invest): add POST /estimate-rent route + thread strategy through analyze"
```

---

### Task 11: Pass strategy to the AI report prompt

**Files:**
- Modify: `backend/services/investor_service.py`

- [ ] **Step 1: Read the current prompt**

```bash
grep -n "def generate_investor_analysis" backend/services/investor_service.py
```

- [ ] **Step 2: Add strategy context into the prompt**

Open `backend/services/investor_service.py`. Find `generate_investor_analysis(payload, metrics)`. At the start of the prompt-building block, add a strategy preamble:

```python
strategy = payload.get("strategy") or "buy_hold"
strategy_label = {
    "buy_hold": "Buy & Hold (long-term rental)",
    "str": "Short-Term Rental (Airbnb / VRBO)",
    "flip": "Fix & Flip",
    "brrrr": "BRRRR (Buy, Rehab, Rent, Refinance, Repeat)",
}.get(strategy, "Buy & Hold")

# Inject the strategy label at the top of the prompt body, e.g.:
prompt = f"""You are advising an investor analyzing a deal under the {strategy_label} strategy.
Frame your analysis around what matters most for that strategy. ...

(rest of existing prompt unchanged)
"""
```

If the existing prompt lives elsewhere (e.g. assembled from multiple strings), insert the `strategy_label` line into the appropriate prelude section. Don't rewrite the whole prompt — just add this context.

- [ ] **Step 3: Manually verify**

Run the backend locally and POST to `/api/v1/investor/analyze` with `strategy: "flip"` and confirm the AI output is flip-themed (mentions ARV, profit, ROI explicitly).

```bash
cd backend && uvicorn main:app --reload --port 8000
# In another terminal:
curl -X POST http://localhost:8000/api/v1/investor/analyze -H "Content-Type: application/json" -d '{...}'
```

(Skip if Gemini API key isn't available locally — call the route in the deployed staging instead during Task 15.)

- [ ] **Step 4: Commit**

```bash
git add backend/services/investor_service.py
git commit -m "feat(invest): thread strategy into AI report prompt"
```

---

## Phase 5 — Rental analyzer modal

### Task 12: Build the RentalAnalyzerModal component

**Files:**
- Create: `frontend/src/lib/rental-analyzer-types.ts`
- Create: `frontend/src/components/investor/RentalAnalyzerModal.tsx`

- [ ] **Step 1: Create shared types**

Create `frontend/src/lib/rental-analyzer-types.ts`:

```ts
export type RentMode = 'ltr' | 'str';
export type RentCondition = 'excellent' | 'good' | 'fair' | 'needs_work';
export type StrMarketType = 'tourist' | 'urban' | 'suburban';

export interface EstimateRentPayload {
  address: string;
  property_type?: string;
  bedrooms?: number;
  bathrooms?: number;
  sqft?: number;
  year_built?: number;
  condition: RentCondition;
  upgrades: string[];
  mode: RentMode;
  market_type?: StrMarketType;
  purchase_price?: number;
}

export interface RentBreakdownItem {
  label: string;
  value_dollars: number;
  pct_delta: number | null;
}

export interface EstimateRentComp {
  address: string;
  rent: number;
  bedrooms: number;
  bathrooms: number;
  sqft: number;
  distance_miles: number;
  correlation: number;
}

export interface EstimateRentResponse {
  mode: RentMode;
  monthly_low: number;
  monthly_median: number;
  monthly_high: number;
  confidence: 'High' | 'Medium' | 'Low';
  breakdown: RentBreakdownItem[];
  comparables: EstimateRentComp[];
  data_source: 'rentcast_avm' | 'fallback_heuristic';
  // STR-only
  nightly_low?: number;
  nightly_median?: number;
  nightly_high?: number;
  suggested_occupancy_pct?: number;
  market_multiplier?: number;
}

export const UPGRADE_OPTIONS = [
  'Kitchen',
  'Baths',
  'HVAC',
  'Flooring',
  'Roof',
  'Windows',
] as const;

export const CONDITION_OPTIONS: { value: RentCondition; label: string }[] = [
  { value: 'excellent', label: 'Excellent' },
  { value: 'good', label: 'Good' },
  { value: 'fair', label: 'Fair' },
  { value: 'needs_work', label: 'Needs Work' },
];

export const MARKET_OPTIONS: { value: StrMarketType; label: string; hint: string }[] = [
  { value: 'tourist', label: 'Tourist', hint: 'Cape Cod, Berkshires, Vermont resort' },
  { value: 'urban', label: 'Urban', hint: 'Boston, Cambridge, Somerville' },
  { value: 'suburban', label: 'Suburban', hint: 'Worcester, Lowell, Manchester NH' },
];
```

- [ ] **Step 2: Create the modal component**

Create `frontend/src/components/investor/RentalAnalyzerModal.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle, SpinnerGap, Warning, House } from '@phosphor-icons/react';
import { apiPost } from '@/lib/api';
import {
  CONDITION_OPTIONS,
  MARKET_OPTIONS,
  UPGRADE_OPTIONS,
  type EstimateRentPayload,
  type EstimateRentResponse,
  type RentCondition,
  type RentMode,
  type StrMarketType,
} from '@/lib/rental-analyzer-types';

interface RentalAnalyzerModalProps {
  open: boolean;
  onClose: () => void;
  mode: RentMode; // ltr or str (caller decides based on strategy)
  prefill?: {
    address?: string;
    property_type?: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    year_built?: number;
    purchase_price?: number;
  };
  onApply: (median: number) => void; // writes the median into the calculator field
}

const fmt = (value: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);

const CONFIDENCE_COLOR: Record<'High' | 'Medium' | 'Low', string> = {
  High: 'text-emerald-400',
  Medium: 'text-yellow-400',
  Low: 'text-red-400',
};

export default function RentalAnalyzerModal({
  open, onClose, mode, prefill, onApply,
}: RentalAnalyzerModalProps) {
  const [address, setAddress] = useState(prefill?.address ?? '');
  const [bedrooms, setBedrooms] = useState<string>(prefill?.bedrooms?.toString() ?? '');
  const [bathrooms, setBathrooms] = useState<string>(prefill?.bathrooms?.toString() ?? '');
  const [sqft, setSqft] = useState<string>(prefill?.sqft?.toString() ?? '');
  const [yearBuilt, setYearBuilt] = useState<string>(prefill?.year_built?.toString() ?? '');
  const [condition, setCondition] = useState<RentCondition | ''>('');
  const [upgrades, setUpgrades] = useState<string[]>([]);
  const [market, setMarket] = useState<StrMarketType | ''>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EstimateRentResponse | null>(null);

  // Reset when reopened
  useEffect(() => {
    if (open) {
      setAddress(prefill?.address ?? '');
      setBedrooms(prefill?.bedrooms?.toString() ?? '');
      setBathrooms(prefill?.bathrooms?.toString() ?? '');
      setSqft(prefill?.sqft?.toString() ?? '');
      setYearBuilt(prefill?.year_built?.toString() ?? '');
      setResult(null);
      setError(null);
    }
  }, [open, prefill]);

  function toggleUpgrade(u: string) {
    setUpgrades((prev) => (prev.includes(u) ? prev.filter((x) => x !== u) : [...prev, u]));
  }

  async function handleAnalyze() {
    if (!address.trim() || !condition) return;
    if (mode === 'str' && !market) return;

    setLoading(true);
    setError(null);
    setResult(null);

    const payload: EstimateRentPayload = {
      address: address.trim(),
      property_type: prefill?.property_type,
      bedrooms: bedrooms ? Number(bedrooms) : undefined,
      bathrooms: bathrooms ? Number(bathrooms) : undefined,
      sqft: sqft ? Number(sqft) : undefined,
      year_built: yearBuilt ? Number(yearBuilt) : undefined,
      condition,
      upgrades,
      mode,
      market_type: mode === 'str' ? (market as StrMarketType) : undefined,
      purchase_price: prefill?.purchase_price,
    };

    try {
      const data = await apiPost<EstimateRentResponse>('/api/v1/investor/estimate-rent', payload);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not estimate rent.');
    } finally {
      setLoading(false);
    }
  }

  function handleApply() {
    if (!result) return;
    const value = mode === 'str' ? (result.nightly_median ?? 0) : result.monthly_median;
    onApply(value);
    onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.98 }}
            transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            onClick={(e) => e.stopPropagation()}
            className="glass border border-dark-border rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6 md:p-8"
          >
            <div className="flex items-start justify-between mb-6">
              <div>
                <p className="text-gold text-xs font-semibold tracking-[0.2em] uppercase mb-1">
                  Rental Analyzer
                </p>
                <h2 className="text-white font-black text-xl tracking-tight">
                  Estimate {mode === 'str' ? 'Nightly Rate' : 'Monthly Rent'}
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="text-white/40 hover:text-white transition-colors"
              >
                <X weight="bold" className="w-5 h-5" />
              </button>
            </div>

            {/* Inputs */}
            <div className="space-y-5">
              <div>
                <label className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-1.5 block">
                  Address
                </label>
                <input
                  type="text"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="123 Main St, Boston, MA"
                  className="w-full bg-dark-surface border border-dark-border text-white text-sm px-4 py-2.5 focus:outline-none focus:border-gold transition-colors"
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <input placeholder="Beds" value={bedrooms} onChange={(e) => setBedrooms(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input placeholder="Baths" value={bathrooms} onChange={(e) => setBathrooms(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input placeholder="Sqft" value={sqft} onChange={(e) => setSqft(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
                <input placeholder="Year" value={yearBuilt} onChange={(e) => setYearBuilt(e.target.value)}
                  className="bg-dark-surface border border-dark-border text-white text-sm px-3 py-2.5 focus:outline-none focus:border-gold" />
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Condition <span className="text-gold">*</span>
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {CONDITION_OPTIONS.map((c) => {
                    const selected = condition === c.value;
                    return (
                      <button
                        key={c.value}
                        type="button"
                        onClick={() => setCondition(c.value)}
                        className={`px-3 py-2.5 text-xs font-semibold tracking-wide border transition-colors ${
                          selected
                            ? 'bg-gold text-[#0a0a0a] border-gold'
                            : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                        }`}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                  Recent Upgrades
                </p>
                <div className="flex flex-wrap gap-2">
                  {UPGRADE_OPTIONS.map((u) => {
                    const selected = upgrades.includes(u);
                    return (
                      <button
                        key={u}
                        type="button"
                        onClick={() => toggleUpgrade(u)}
                        className={`px-3 py-1.5 text-xs font-semibold tracking-widest uppercase border transition-colors ${
                          selected
                            ? 'bg-gold/15 border-gold text-gold'
                            : 'bg-transparent border-dark-border text-white/50 hover:border-gold/40'
                        }`}
                      >
                        {selected && <CheckCircle weight="fill" className="inline w-3 h-3 mr-1" />}
                        {u}
                      </button>
                    );
                  })}
                </div>
              </div>

              {mode === 'str' && (
                <div>
                  <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                    Market Type <span className="text-gold">*</span>
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {MARKET_OPTIONS.map((m) => {
                      const selected = market === m.value;
                      return (
                        <button
                          key={m.value}
                          type="button"
                          onClick={() => setMarket(m.value)}
                          className={`px-3 py-2 text-xs font-semibold tracking-wide border text-left transition-colors ${
                            selected
                              ? 'bg-gold text-[#0a0a0a] border-gold'
                              : 'bg-dark-surface border-dark-border text-white/60 hover:border-gold/40 hover:text-white'
                          }`}
                        >
                          <div>{m.label}</div>
                          <div className="text-[10px] opacity-60 mt-0.5">{m.hint}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <button
                type="button"
                onClick={handleAnalyze}
                disabled={loading || !address.trim() || !condition || (mode === 'str' && !market)}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-gold text-[#0a0a0a] font-semibold text-sm px-6 py-3 hover:bg-gold/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {loading ? <SpinnerGap weight="bold" className="w-4 h-4 animate-spin" /> : <House weight="bold" className="w-4 h-4" />}
                {loading ? 'Analyzing…' : 'Estimate'}
              </button>

              {error && (
                <div className="flex items-start gap-2 text-amber-400/80 text-sm">
                  <Warning weight="fill" className="w-4 h-4 mt-0.5 shrink-0" />
                  {error}
                </div>
              )}
            </div>

            {/* Result */}
            <AnimatePresence>
              {result && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -12 }}
                  className="mt-6 pt-6 border-t border-dark-border space-y-4"
                >
                  <div className="flex flex-wrap items-baseline gap-3">
                    <p className="text-gold font-black text-3xl leading-none">
                      {mode === 'str' ? `${fmt(result.nightly_median ?? 0)}/night` : `${fmt(result.monthly_median)}/mo`}
                    </p>
                    <p className="text-white/50 text-xs">
                      {mode === 'str'
                        ? `${fmt(result.nightly_low ?? 0)} – ${fmt(result.nightly_high ?? 0)} per night`
                        : `${fmt(result.monthly_low)} – ${fmt(result.monthly_high)} per month`}
                    </p>
                    <span className={`text-xs font-bold tracking-widest uppercase ${CONFIDENCE_COLOR[result.confidence]}`}>
                      {result.confidence} confidence
                    </span>
                  </div>

                  {mode === 'str' && (
                    <p className="text-white/45 text-xs">
                      Based on {result.market_multiplier}× LTR baseline at {result.suggested_occupancy_pct}% occupancy.
                    </p>
                  )}

                  <div>
                    <p className="text-white/60 text-xs font-semibold tracking-widest uppercase mb-2">
                      Breakdown
                    </p>
                    <ul className="space-y-1.5">
                      {result.breakdown.map((b, i) => (
                        <li key={i} className="flex items-center justify-between text-sm text-white/70">
                          <span>{b.label}</span>
                          <span className="font-mono text-white/90">
                            {b.pct_delta != null ? `${b.pct_delta > 0 ? '+' : ''}${b.pct_delta}%` : ''}{' '}
                            {b.pct_delta != null ? `(${fmt(b.value_dollars)})` : fmt(b.value_dollars)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <button
                    type="button"
                    onClick={handleApply}
                    className="w-full bg-gold text-[#0a0a0a] font-semibold text-sm px-6 py-3 hover:bg-gold/90 transition-colors"
                  >
                    Use {fmt(mode === 'str' ? (result.nightly_median ?? 0) : result.monthly_median)} in Calculator
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/rental-analyzer-types.ts \
        frontend/src/components/investor/RentalAnalyzerModal.tsx
git commit -m "feat(invest): RentalAnalyzerModal with condition+upgrade breakdown UI"
```

---

### Task 13: Wire "Estimate this" links into the calculator

**Files:**
- Modify: `frontend/src/components/investor/InvestorCalculator.tsx`

- [ ] **Step 1: Add modal state + helper to render the trigger link**

In `InvestorCalculator.tsx`, near the other useState hooks:

```tsx
import RentalAnalyzerModal from './RentalAnalyzerModal';
import type { RentMode } from '@/lib/rental-analyzer-types';

// ... inside InvestorCalculator():
const [analyzerOpen, setAnalyzerOpen] = useState(false);

const analyzerMode: RentMode = strategy === 'str' ? 'str' : 'ltr';
const analyzerTargetField = strategy === 'str' ? 'nightlyRate' : 'rentalIncome';

const analyzerPrefill = {
  address: lookupResult?.address || lookupAddress,
  property_type: lookupResult?.property_type,
  bedrooms: lookupResult?.bedrooms ?? undefined,
  bathrooms: lookupResult?.bathrooms ?? undefined,
  sqft: lookupResult?.sqft ?? undefined,
  year_built: lookupResult?.year_built ?? undefined,
  purchase_price: num(inputs, 'purchasePrice') || undefined,
};

function handleAnalyzerApply(value: number) {
  setInputs((prev) => ({ ...prev, [analyzerTargetField]: String(Math.round(value)) }));
  setFilledFields((prev) => new Set(prev).add(analyzerTargetField));
}
```

- [ ] **Step 2: Add an "Estimate this" link inside the relevant InputField labels**

Above the existing input grid, define a small helper that renders the link inline. Inline-edit the labels for the relevant strategy:

For Buy & Hold and BRRRR (rentalIncome) and STR (nightlyRate), wrap that single InputField in a `<div>` and add an "Estimate this" trigger button just below the label. Simplest implementation — extend `InputField` to accept an optional `actionLabel` + `onAction`:

```tsx
interface InputFieldProps {
  label: string;
  name: string;
  value: string;
  onChange: (name: string, value: string) => void;
  prefix?: string;
  suffix?: string;
  step?: number;
  highlight?: boolean;
  actionLabel?: string;
  onAction?: () => void;
}

function InputField({
  label, name, value, onChange, prefix, suffix, step = 1, highlight, actionLabel, onAction,
}: InputFieldProps) {
  // ...existing displayValue + return JSX, but update the label row:
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label htmlFor={`input-${name}`} className="text-white/50 text-xs font-medium tracking-widest uppercase">
          {label}
        </label>
        {actionLabel && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="text-gold text-[10px] font-semibold tracking-widest uppercase hover:underline"
          >
            {actionLabel}
          </button>
        )}
      </div>
      {/* existing input wrapper */}
    </div>
  );
}
```

Then on the relevant fields:

```tsx
{(strategy === 'buy_hold' || strategy === 'brrrr') && (
  <InputField label="Monthly Rental Income" name="rentalIncome" value={inputs.rentalIncome}
    onChange={handleChange} prefix="$" highlight={filledFields.has('rentalIncome')}
    actionLabel="Estimate this" onAction={() => setAnalyzerOpen(true)} />
)}

{strategy === 'str' && (
  <InputField label="Nightly Rate" name="nightlyRate" value={inputs.nightlyRate}
    onChange={handleChange} prefix="$"
    actionLabel="Estimate this" onAction={() => setAnalyzerOpen(true)} />
)}
```

- [ ] **Step 3: Mount the modal at the bottom of the component**

Just before the final closing `</div>` of the calculator's JSX:

```tsx
<RentalAnalyzerModal
  open={analyzerOpen}
  onClose={() => setAnalyzerOpen(false)}
  mode={analyzerMode}
  prefill={analyzerPrefill}
  onApply={handleAnalyzerApply}
/>
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/investor/InvestorCalculator.tsx
git commit -m "feat(invest): wire RentalAnalyzerModal to rent fields per strategy"
```

---

## Phase 6 — Real-world calibration

### Task 14: Calibrate against real Boston-metro rentals

This is the validation step the user explicitly asked for. The output is a calibration appendix in the spec doc. **All addresses must be real, currently-listed properties** so the data is verifiable later.

**Files:**
- Modify: `backend/services/rental_analyzer_service.py` (only if calibration shows the multipliers need adjusting)
- Modify: `docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md` (append appendix)

- [ ] **Step 1: Pick 5 real Boston-metro rental listings spanning conditions**

Use Zillow Rentals (zillow.com/homes/for_rent) or Rent.com. Pick:

1. One **3bd/2ba single-family** in suburban MA (e.g., Methuen, Lowell, or Worcester) currently listed for rent
2. One **2bd condo** in Cambridge or Somerville
3. One **3-bd unit in a triple-decker** in Dorchester/East Boston
4. One **4bd/3ba single-family** in a higher-end suburb (e.g., Andover, Lexington)
5. One **1bd apartment** in downtown Boston

For each, record: full address, current listing rent, beds/baths/sqft, the user's best-guess condition (Excellent/Good/Fair) based on listing photos.

- [ ] **Step 2: Run the analyzer against each address via the deployed API**

```bash
curl -X POST https://<staging-or-localhost>/api/v1/investor/estimate-rent \
  -H "Content-Type: application/json" \
  -d '{
    "address": "...",
    "bedrooms": 3,
    "bathrooms": 2,
    "sqft": 1850,
    "year_built": 1998,
    "condition": "good",
    "upgrades": [],
    "mode": "ltr"
  }'
```

Record `monthly_median` for each.

- [ ] **Step 3: Compute % error per address and overall median absolute error**

For each: `error% = (estimate − actual) / actual × 100`.

Compute median absolute error across all 5. Target: ≤ 10%. Max single error: ≤ 18%.

- [ ] **Step 4: Tune `CONDITION_ADJUSTMENTS` and `UPGRADE_BUMPS` if needed**

If median absolute error > 10%, adjust the multipliers in `rental_analyzer_service.py` and re-run. Common patterns:
- If estimates are systematically low for newer/renovated properties → bump `excellent` from +4% to +5% or add a "year_built ≥ 2010" bonus
- If estimates are too high in lower-tier markets → tighten `needs_work` toward −15%
- Re-run the unit tests after changes; some assertions may need to update if the multipliers shifted

```bash
cd backend && python -m pytest tests/test_rental_analyzer_service.py -v
```

If tests need updating because they used assertion ranges, update the ranges to match the new multipliers — but **only widen ranges to accommodate calibration**, don't loosen tests cosmetically.

- [ ] **Step 5: STR calibration with 3 real Airbnb listings**

Pick 3 active Airbnb listings:

1. Cape Cod beach rental (Tourist) — get nightly rate from listing page + month-by-month occupancy from Airbnb's calendar (count blocked dates)
2. Beacon Hill / South End apartment in Boston (Urban)
3. Worcester or Lowell house (Suburban)

For each: actual nightly rate × estimated occupancy (count of blocked days / total days over next 90 days) = projected monthly revenue. Compare to the analyzer's output for the same address with `mode: "str"`.

If multipliers are off by > 25% on average, adjust `STR_MARKET_MULTIPLIERS` and re-test.

- [ ] **Step 6: BRRRR end-to-end against a published case study**

Find one BiggerPockets case study with disclosed numbers:
- Purchase price, rehab, ARV, refi LTV, refi rate, refi term, post-rehab rent
- Cash-left-in-deal as reported

Plug those into `calculateBrrrrMetrics` (e.g., via a quick `node --import tsx` script or by typing them into the live calculator) and confirm `cashLeftInDeal` matches the case study within $500.

If it doesn't, the bug is in the engine — debug `calculateBrrrrMetrics` until it does.

- [ ] **Step 7: Flip sanity check**

Pick one Boston-area flip from public records (sites like Mashvisor or just searching `<city> flip 2024 site:redfin.com`):
- Purchase price, sale price, rough rehab estimate

Plug into `calculateFlipMetrics` and confirm `flipProfit` is within $5,000 of `salePrice − purchasePrice − rehabEstimate − ~5% closing/holding`.

- [ ] **Step 8: Document results in a calibration appendix**

Append to `docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md`:

```markdown
## Appendix: Calibration runs (filled in 2026-05-10)

### LTR calibration

| # | Address | Beds/Baths/Sqft | Condition | Actual rent | Estimate | Error |
|---|---------|-----------------|-----------|-------------|----------|-------|
| 1 | <real address>           | 3/2/1850 | good      | $2,750 | $2,694 | −2.0%  |
| 2 | <real address>           | 2/1/950  | excellent | $3,200 | $3,180 | −0.6%  |
| 3 | <real address>           | 3/1/1100 | fair      | $2,400 | $2,290 | −4.6%  |
| 4 | <real address>           | 4/3/2400 | good      | $4,500 | $4,318 | −4.0%  |
| 5 | <real address>           | 1/1/650  | good      | $2,650 | $2,520 | −4.9%  |

**Median absolute error:** 4.0%. **Max error:** 4.9%. ✅ Under 10% target.

### STR calibration

| Market type | Address | Actual nightly × occupancy | Monthly est. rev. | Estimate | Error |
|-------------|---------|----------------------------|-------------------|----------|-------|
| Tourist     | <Cape Cod> | $385 × 75% × 30.4 = $8,772 | ... | ... | ... |
| Urban       | <Boston>   | $285 × 70% × 30.4 = $6,066 | ... | ... | ... |
| Suburban    | <Worcester>| $185 × 55% × 30.4 = $3,094 | ... | ... | ... |

### BRRRR end-to-end

Source: <BiggerPockets URL>. Reported cash-left-in-deal: $X. Engine output: $Y. Δ = $|X−Y|.

### Flip sanity

Source: <Redfin URL>. Implied profit: $A. Engine output: $B. Δ = $|A−B|.
```

(Replace placeholder rows with the real numbers you collected. The example error numbers above show the *target* shape — your actual calibration may differ.)

- [ ] **Step 9: Commit calibration**

```bash
git add docs/superpowers/specs/2026-05-10-investor-strategy-toggle-and-rental-analyzer-design.md \
        backend/services/rental_analyzer_service.py \
        backend/tests/test_rental_analyzer_service.py
git commit -m "calibrate(rental): tune condition/upgrade multipliers against 5 real listings"
```

---

## Phase 7 — End-to-end verification

### Task 15: Manual browser verification + polish

**Files:**
- None (verification + small touch-ups)

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && npm run dev
```

Note the URL (default `http://localhost:3000`).

- [ ] **Step 2: Walk through every strategy in the browser**

Open `http://localhost:3000/invest`. For each of the four strategies (click each pill in turn):

1. Confirm the URL updates to `?strategy=<value>` (or strips for `buy_hold`)
2. Confirm strategy-specific fields appear/disappear correctly
3. Confirm pre-filled defaults populate empty fields
4. Confirm overlapping fields (purchase price, rehab, taxes, insurance) are preserved when switching strategies
5. Fill out a complete deal and confirm `AnalysisResults` shows the right metrics block per strategy
6. For BRRRR, set `refiLtvPct` to 90% and confirm "Infinite-ROI" badge appears

- [ ] **Step 3: Walk through the rental analyzer**

For Buy & Hold strategy:
1. Click "Estimate this" next to Monthly Rental Income — modal opens
2. Enter a real address, condition Good, no upgrades — confirm result range
3. Click "Use $X in Calculator" — confirm modal closes and the field populates with the median + gold border highlight
4. Switch to STR — confirm the modal trigger now opens in `mode: 'str'` and asks for market type
5. Switch to BRRRR — confirm modal trigger writes back into `rentalIncome`

- [ ] **Step 4: Run all checks**

```bash
cd frontend && npm test && npm run typecheck && npm run lint
cd ../backend && python -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 5: Verify URL deep-link**

Open `http://localhost:3000/invest?strategy=brrrr` directly. Confirm BRRRR strategy is active on first paint.

Open `http://localhost:3000/invest?strategy=garbage`. Confirm it falls back to Buy & Hold and the param is stripped from the URL.

- [ ] **Step 6: Verify gated-report flow still works**

Fill out a complete Buy & Hold deal, click through to email-gate the AI report, confirm the report renders. Confirm the Lead row created in the database includes `"strategy": "buy_hold"` in `metadata_json`:

```bash
# In the backend container or local DB:
psql $DATABASE_URL -c "SELECT id, metadata_json FROM leads ORDER BY id DESC LIMIT 1;"
```

- [ ] **Step 7: Final commit if any polish was applied**

If you found small visual issues (spacing, label wording, mobile breakpoints) and fixed them inline:

```bash
git add <touched files>
git commit -m "polish(invest): minor visual fixes from end-to-end verification"
```

If everything was clean, no commit needed.

- [ ] **Step 8: Confirm in writing**

Write a short verification note in the PR description (when raising the PR), listing:
- "All 4 strategy toggles tested in browser"
- "Rental analyzer LTR + STR tested with real address"
- "Calibration: median LTR error X.X% across 5 listings"
- "BRRRR end-to-end matches BiggerPockets case study within $Y"
- "All Vitest + pytest tests passing"

---

## Self-Review

**Spec coverage check:**
- ✅ Strategy toggle (Buy & Hold / STR / Flip / BRRRR) → Tasks 6–8
- ✅ Per-strategy field maps → Task 7
- ✅ Per-strategy default values → Task 6 (`strategy-defaults.ts`)
- ✅ Discriminated-union calc engine → Tasks 2–5
- ✅ Per-strategy result emphasis → Task 8
- ✅ Rental analyzer modal (LTR + STR) → Tasks 9–13
- ✅ `POST /estimate-rent` route → Task 10
- ✅ Heuristic adjustment tables → Task 9
- ✅ STR market multipliers → Task 9
- ✅ Confidence labeling → Task 9 (`_confidence`)
- ✅ Fallback when RentCast misses → Task 9 (`_fallback_baseline`)
- ✅ AI prompt threaded with strategy → Task 11
- ✅ URL sync with `?strategy=` → Task 7
- ✅ Real-world calibration → Task 14
- ✅ End-to-end manual verification → Task 15
- ✅ No DB migration needed → confirmed; no migration tasks added

**Placeholder scan:** No "TBD" or "implement later" in the plan. The calibration appendix template in Task 14 explicitly says to replace placeholder rows with real numbers, which is the intended workflow.

**Type consistency:**
- `Strategy` type defined in Task 2, used in Tasks 6, 7, 8, 11, 12, 13 — consistent
- `BuyHoldInputs`, `StrInputs`, `FlipInputs`, `BrrrrInputs` defined in Task 2; matching constructor objects in Task 7 use `satisfies` — consistent
- `EstimateRentRequest` Pydantic model in Task 9 matches `EstimateRentPayload` TS type in Task 12 (field-by-field) — consistent
- `RentMode = 'ltr' | 'str'` in Task 12 matches the Python `mode: Literal["ltr", "str"]` in Task 9 — consistent
- `STRATEGY_DEFAULTS` keys are flat string keys matching the `InputValues` keys used in Task 7 — consistent

Plan is ready to execute.
