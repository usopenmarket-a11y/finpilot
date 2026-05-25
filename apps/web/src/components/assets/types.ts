export type AssetType = 'gold' | 'silver' | 'car' | 'property' | 'foreign_currency' | 'stock' | 'other';

export interface Asset {
  id: string;
  user_id: string;
  name: string;
  asset_type: AssetType;
  quantity: number;
  unit: string;
  purchase_price_egp: number;
  purchase_date: string;
  current_value_egp: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Asset types that support live price calculation (price per unit from API)
export const AUTO_PRICE_TYPES = new Set<AssetType>(['gold', 'silver']);

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  gold: 'Gold',
  silver: 'Silver',
  car: 'Car',
  property: 'Property',
  foreign_currency: 'Foreign Currency',
  stock: 'Stocks',
  other: 'Other',
};

export const ASSET_TYPE_ICONS: Record<AssetType, string> = {
  gold: '🥇',
  silver: '🥈',
  car: '🚗',
  property: '🏠',
  foreign_currency: '💵',
  stock: '📈',
  other: '📦',
};

export const DEFAULT_UNITS: Record<AssetType, string> = {
  gold: 'grams',
  silver: 'grams',
  car: 'units',
  property: 'sqm',
  foreign_currency: 'units',
  stock: 'shares',
  other: 'units',
};

export function resolveCurrentValue(asset: Asset, livePrices: Record<string, number>): number {
  if (AUTO_PRICE_TYPES.has(asset.asset_type)) {
    const pricePerGram = livePrices[asset.asset_type];
    if (pricePerGram) return asset.quantity * pricePerGram;
  }
  // Fall back to manually entered current value, then purchase price
  return asset.current_value_egp ?? asset.purchase_price_egp;
}

export function gainLoss(asset: Asset, livePrices: Record<string, number>): number {
  return resolveCurrentValue(asset, livePrices) - asset.purchase_price_egp;
}
