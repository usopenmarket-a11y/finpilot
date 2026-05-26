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
  currency_code: string | null;
  is_gift: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Asset types that support live price calculation (price per unit from API)
// foreign_currency uses livePrices[currency_code] keyed by ISO code (e.g. 'USD')
export const AUTO_PRICE_TYPES = new Set<AssetType>(['gold', 'silver', 'foreign_currency']);

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
  if (asset.asset_type === 'foreign_currency' && asset.currency_code) {
    const rate = livePrices[asset.currency_code];
    if (rate) return asset.quantity * rate;
  } else if (asset.asset_type === 'gold' || asset.asset_type === 'silver') {
    const pricePerGram = livePrices[asset.asset_type];
    if (pricePerGram) return asset.quantity * pricePerGram;
  }
  // Fall back to manually entered current value, then purchase price
  return asset.current_value_egp ?? asset.purchase_price_egp;
}

export function gainLoss(asset: Asset, livePrices: Record<string, number>): number {
  return resolveCurrentValue(asset, livePrices) - asset.purchase_price_egp;
}

export function gainLossPct(asset: Asset, livePrices: Record<string, number>): number | null {
  if (asset.is_gift || asset.purchase_price_egp === 0) return null; // no meaningful %
  return (gainLoss(asset, livePrices) / asset.purchase_price_egp) * 100;
}
