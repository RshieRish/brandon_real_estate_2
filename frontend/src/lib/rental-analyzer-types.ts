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
