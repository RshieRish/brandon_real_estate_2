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

// ─── Flip ──────────────────────────────────────────────────────────────────
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

// ─── STR (Short-Term Rental) ───────────────────────────────────────────────
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

// ─── BRRRR (Buy, Rehab, Rent, Refinance, Repeat) ───────────────────────────
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
  const monthlyNOI = inputs.rentalIncome - monthlyHoldExpenses;
  const noi = monthlyNOI * 12;
  const postRefiMonthlyCashFlow = monthlyNOI - vacancyAllowance - postRefiMortgage;
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

// ─── Dispatch wrapper (will grow as strategies are added) ───────────────────
export function calculateMetrics(inputs: InvestorInputs): InvestorMetrics {
  switch (inputs.strategy) {
    case 'buy_hold':
      return calculateBuyHoldMetrics(inputs);
    case 'flip':
      return calculateFlipMetrics(inputs);
    case 'str':
      return calculateStrMetrics(inputs);
    case 'brrrr':
      return calculateBrrrrMetrics(inputs);
    default: {
      const _exhaustive: never = inputs;
      throw new Error(`Strategy "${(_exhaustive as InvestorInputs).strategy}" not implemented yet`);
    }
  }
}
