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
  // NOI follows the industry convention (gross income minus operating expenses)
  // and is the basis for Cap Rate. Vacancy is applied separately to cash flow.
  const monthlyNOI = inputs.rentalIncome - monthlyExpenses;
  const noi = monthlyNOI * 12;
  const monthlyCashFlow = monthlyNOI - vacancyAllowance - monthlyMortgage;
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
