export interface InvestorLeadCapture {
  name: string;
  email: string;
  phone: string;
}

export interface InvestorHoldScenario {
  years: number;
  equity: number;
  cumulative_cash_flow: number;
  exit_value: number;
}

export interface InvestorAiReport {
  ai_explanation?: string;
  hold_scenarios?: InvestorHoldScenario[];
  exit_comparison?: {
    sell?: string;
    refinance?: string;
    exchange_1031?: string;
  };
  sensitivity?: {
    tax_increase_10pct?: number;
    vacancy_10pct?: number;
    rent_drop_5pct?: number;
  };
  verdict?: string;
  verdict_reason?: string;
  disclaimer?: string;
}

export interface InvestorAnalysisResponse {
  report: InvestorAiReport;
}
