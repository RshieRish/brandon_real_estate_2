export interface InvestorInputs {
  purchasePrice: number;
  rehabCost: number;
  arv: number;         // After-repair value
  holdMonths: number;
  rentalIncome: number; // Monthly gross
  propertyTax: number;  // Annual
  insurance: number;    // Annual
  downPaymentPct: number; // e.g. 25
  interestRate: number;   // e.g. 7
  loanTermYears: number;  // e.g. 30
}

export interface InvestorMetrics {
  // Flip
  loanStructure: 'interest_only' | 'amortized';
  flipProfit: number;
  flipROI: number;          // %
  flipAnnualizedROI: number; // %
  maxAllowableOffer: number; // 80% rule
  holdingCosts: number;
  closingCosts: number;
  totalProjectCost: number;

  // Rental / BRRRR
  monthlyMortgage: number;
  monthlyCashFlow: number;
  annualCashFlow: number;
  cashOnCashReturn: number; // %
  capRate: number;          // %
  grm: number;              // Gross Rent Multiplier
  noi: number;              // Net Operating Income (annual)

  // Equity
  totalEquity: number;
  equityMultiple: number;
}

export function calculateMetrics(inputs: InvestorInputs): InvestorMetrics {
  const {
    purchasePrice, rehabCost, arv, holdMonths,
    rentalIncome, propertyTax, insurance,
    downPaymentPct, interestRate, loanTermYears,
  } = inputs;

  // Prevent division by zero / NaN from zero inputs
  const safeDivide = (n: number, d: number) => (d === 0 ? 0 : n / d);

  const totalInvested = purchasePrice + rehabCost;
  const downPaymentRate = downPaymentPct / 100;
  const interestRateDecimal = interestRate / 100;
  const downPayment = purchasePrice * downPaymentRate;
  const loanAmount = purchasePrice - downPayment;
  const monthlyRate = interestRateDecimal / 12;
  const numPayments = Math.max(loanTermYears * 12, 1);
  const isShortTermInvestorDebt = loanTermYears <= 2;
  const loanStructure: InvestorMetrics['loanStructure'] = isShortTermInvestorDebt
    ? 'interest_only'
    : 'amortized';
  const monthlyMortgage = isShortTermInvestorDebt
    ? loanAmount * monthlyRate
    : monthlyRate === 0
      ? safeDivide(loanAmount, numPayments)
      : loanAmount *
        (monthlyRate * Math.pow(1 + monthlyRate, numPayments)) /
        (Math.pow(1 + monthlyRate, numPayments) - 1);

  // Flip
  const holdingCosts = monthlyMortgage * holdMonths;
  const closingCosts = (purchasePrice * 0.015) + (arv * 0.0125);
  const totalProjectCost = totalInvested + holdingCosts + closingCosts;
  const flipProfit = arv - totalProjectCost;
  const cashInvestedFlip = downPayment + rehabCost + holdingCosts + closingCosts;
  const flipROI = safeDivide(flipProfit, cashInvestedFlip) * 100;
  const flipAnnualizedROI = (flipROI / holdMonths) * 12;
  const maxAllowableOffer = arv * 0.8 - rehabCost;

  // Rental
  const monthlyExpenses = (propertyTax + insurance) / 12;
  const vacancyAllowance = rentalIncome * 0.08;
  const monthlyNOI = rentalIncome - vacancyAllowance - monthlyExpenses;
  const noi = monthlyNOI * 12;
  const monthlyCashFlow = monthlyNOI - monthlyMortgage;
  const annualCashFlow = monthlyCashFlow * 12;
  const cashInvestedRental = downPayment + rehabCost;
  const cashOnCashReturn = safeDivide(annualCashFlow, cashInvestedRental) * 100;
  const capRate = safeDivide(noi, purchasePrice) * 100;
  const grm = safeDivide(purchasePrice, rentalIncome * 12);

  // Equity
  const totalEquity = arv - loanAmount;
  const equityMultiple = safeDivide(arv, cashInvestedRental);

  return {
    loanStructure, flipProfit, flipROI, flipAnnualizedROI, maxAllowableOffer,
    holdingCosts, closingCosts, totalProjectCost,
    monthlyMortgage, monthlyCashFlow, annualCashFlow,
    cashOnCashReturn, capRate, grm, noi,
    totalEquity, equityMultiple,
  };
}
