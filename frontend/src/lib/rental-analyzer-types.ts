export type RentMode = 'ltr' | 'str';
export type RentCondition = 'excellent' | 'good' | 'fair' | 'needs_work';
export type StrMarketType = 'tourist' | 'urban' | 'suburban';

export type PropertyType =
  | 'single_family'
  | 'duplex'
  | 'townhouse'
  | 'condo'
  | 'multi_2_4_unit'
  | 'multi_5plus_unit'
  | 'adu';

export type Amenity =
  | 'in_unit_laundry'
  | 'off_street_parking'
  | 'garage'
  | 'central_ac'
  | 'private_outdoor'
  | 'dishwasher'
  | 'pet_friendly';

export interface EstimateRentPayload {
  address: string;
  property_type: PropertyType;
  bedrooms?: number;
  bathrooms?: number;
  sqft?: number;
  year_built?: number;
  condition: RentCondition;
  upgrades: string[];
  amenities: Amenity[];
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
  property_type: PropertyType | null;
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

export const PROPERTY_TYPE_OPTIONS: { value: PropertyType; label: string }[] = [
  { value: 'single_family',    label: 'Single Family' },
  { value: 'duplex',           label: 'Duplex' },
  { value: 'townhouse',        label: 'Townhouse' },
  { value: 'condo',            label: 'Condo' },
  { value: 'multi_2_4_unit',   label: 'Small Multi (2-4 unit)' },
  { value: 'multi_5plus_unit', label: 'Apartment Building (5+ unit)' },
  { value: 'adu',              label: 'ADU' },
];

export const AMENITY_OPTIONS: { value: Amenity; label: string }[] = [
  { value: 'in_unit_laundry',    label: 'In-Unit Laundry' },
  { value: 'off_street_parking', label: 'Off-Street Parking' },
  { value: 'garage',             label: 'Garage' },
  { value: 'central_ac',         label: 'Central AC' },
  { value: 'private_outdoor',    label: 'Private Outdoor Space' },
  { value: 'dishwasher',         label: 'Dishwasher' },
  { value: 'pet_friendly',       label: 'Pet-Friendly' },
];
