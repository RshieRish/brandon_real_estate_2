import { describe, it, expect } from 'vitest';
import {
  parseInputs,
  EMPTY_INPUTS,
  type InputValues,
} from './InvestorCalculator';

const baseValues: InputValues = {
  ...EMPTY_INPUTS,
  purchasePrice: '300000',
  rehabCost: '20000',
  propertyTax: '5000',
  insurance: '1500',
  downPaymentPct: '25',
  interestRate: '7',
  loanTermYears: '30',
};

describe('parseInputs', () => {
  describe('buy_hold', () => {
    it('returns parsed inputs when all required fields are present', () => {
      const v: InputValues = { ...baseValues, holdYears: '5', rentalIncome: '2500' };
      const result = parseInputs('buy_hold', v);
      expect(result).not.toBeNull();
      expect(result?.strategy).toBe('buy_hold');
    });

    it('returns null when holdYears is missing', () => {
      const v: InputValues = { ...baseValues, rentalIncome: '2500' };
      expect(parseInputs('buy_hold', v)).toBeNull();
    });

    it('returns null when purchasePrice is missing', () => {
      const v: InputValues = { ...baseValues, purchasePrice: '', holdYears: '5', rentalIncome: '2500' };
      expect(parseInputs('buy_hold', v)).toBeNull();
    });
  });

  describe('str', () => {
    it('returns parsed inputs when all required fields are present', () => {
      const v: InputValues = { ...baseValues, nightlyRate: '250' };
      const result = parseInputs('str', v);
      expect(result).not.toBeNull();
      expect(result?.strategy).toBe('str');
    });

    it('returns null when nightlyRate is missing', () => {
      const v: InputValues = { ...baseValues };
      expect(parseInputs('str', v)).toBeNull();
    });
  });

  describe('flip', () => {
    it('returns parsed inputs when all required fields are present', () => {
      const v: InputValues = { ...baseValues, arv: '450000', holdMonths: '6' };
      const result = parseInputs('flip', v);
      expect(result).not.toBeNull();
      expect(result?.strategy).toBe('flip');
    });

    it('returns null when arv is missing', () => {
      const v: InputValues = { ...baseValues, holdMonths: '6' };
      expect(parseInputs('flip', v)).toBeNull();
    });

    it('returns null when holdMonths is missing', () => {
      const v: InputValues = { ...baseValues, arv: '450000' };
      expect(parseInputs('flip', v)).toBeNull();
    });
  });

  describe('brrrr', () => {
    it('returns parsed inputs when all required fields are present', () => {
      const v: InputValues = {
        ...baseValues,
        arv: '360000',
        holdMonthsBeforeRefi: '6',
        refiTermYears: '30',
        rentalIncome: '2800',
      };
      const result = parseInputs('brrrr', v);
      expect(result).not.toBeNull();
      expect(result?.strategy).toBe('brrrr');
    });

    it('returns null when arv is missing', () => {
      const v: InputValues = {
        ...baseValues,
        holdMonthsBeforeRefi: '6',
        refiTermYears: '30',
      };
      expect(parseInputs('brrrr', v)).toBeNull();
    });

    it('returns null when refiTermYears is missing', () => {
      const v: InputValues = {
        ...baseValues,
        arv: '360000',
        holdMonthsBeforeRefi: '6',
      };
      expect(parseInputs('brrrr', v)).toBeNull();
    });
  });
});
