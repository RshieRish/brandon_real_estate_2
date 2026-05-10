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
