export interface InvestorInputs {
  purchasePrice: number;
  rehabCost: number;
  arv: number;         // After-repair value
  holdMonths: number;
  rentalIncome: number; // Monthly gross
  propertyTax: number;  // Annual
  insurance: number;    // Annual
  downPaymentPct: number; // e.g. 0.25
  interestRate: number;   // e.g. 0.07
  loanTermYears: number;  // e.g. 30
}

export interface InvestorMetrics {
  // Flip
  flipProfit: number;
  flipROI: number;          // %
  flipAnnualizedROI: number; // %
  maxAllowableOffer: number; // 70% rule

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
  const downPayment = purchasePrice * downPaymentPct;
  const loanAmount = purchasePrice - downPayment;
  const monthlyRate = interestRate / 12;
  const numPayments = loanTermYears * 12;
  const monthlyMortgage =
    monthlyRate === 0
      ? safeDivide(loanAmount, numPayments)
      : loanAmount *
        (monthlyRate * Math.pow(1 + monthlyRate, numPayments)) /
        (Math.pow(1 + monthlyRate, numPayments) - 1);

  // Flip
  const holdingCosts = monthlyMortgage * holdMonths;
  const flipProfit = arv - totalInvested - holdingCosts;
  const cashInvestedFlip = downPayment + rehabCost + holdingCosts;
  const flipROI = safeDivide(flipProfit, cashInvestedFlip) * 100;
  const flipAnnualizedROI = (flipROI / holdMonths) * 12;
  const maxAllowableOffer = arv * 0.7 - rehabCost;

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
    flipProfit, flipROI, flipAnnualizedROI, maxAllowableOffer,
    monthlyMortgage, monthlyCashFlow, annualCashFlow,
    cashOnCashReturn, capRate, grm, noi,
    totalEquity, equityMultiple,
  };
}
