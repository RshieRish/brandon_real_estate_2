import { describe, it, expect } from 'vitest';
import {
  calculateBuyHoldMetrics,
  calculateFlipMetrics,
  calculateStrMetrics,
  calculateMetrics,
  type BuyHoldInputs,
  type FlipInputs,
  type StrInputs,
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
    expect(m.capRate).toBeCloseTo(7.61, 1);
  });

  it('flags interest_only loan structure when term ≤ 2 years', () => {
    const m = calculateBuyHoldMetrics({ ...baseInputs, loanTermYears: 1 });
    expect(m.loanStructure).toBe('interest_only');
  });

  it('returns 0 GRM when annual rent is 0', () => {
    const m = calculateBuyHoldMetrics({ ...baseInputs, rentalIncome: 0 });
    expect(m.grm).toBe(0);
  });

  it('produces finite cashflow with no rental income', () => {
    const m = calculateBuyHoldMetrics({ ...baseInputs, rentalIncome: 0 });
    expect(Number.isFinite(m.monthlyCashFlow)).toBe(true);
  });

  it('dispatch wrapper routes buy_hold inputs correctly', () => {
    const m = calculateMetrics(baseInputs);
    expect(m.strategy).toBe('buy_hold');
  });
});

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
    expect(m.breakEvenOccupancyPct).toBeGreaterThanOrEqual(0);
    expect(m.breakEvenOccupancyPct).toBeLessThanOrEqual(100);
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
