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
