'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Button } from '@/components/ui/button';
import type { Asset, AssetType } from './types';
import { ASSET_TYPE_LABELS, ASSET_TYPE_ICONS, DEFAULT_UNITS, AUTO_PRICE_TYPES } from './types';

interface AssetFormProps {
  asset?: Asset;
  onSaved: () => void;
  onCancel: () => void;
}

const ASSET_TYPES: AssetType[] = ['gold', 'silver', 'car', 'property', 'foreign_currency', 'stock', 'other'];

export function AssetForm({ asset, onSaved, onCancel }: AssetFormProps) {
  const isEdit = !!asset;

  const [name, setName] = useState(asset?.name ?? '');
  const [assetType, setAssetType] = useState<AssetType>(asset?.asset_type ?? 'gold');
  const [quantity, setQuantity] = useState(asset?.quantity.toString() ?? '1');
  const [unit, setUnit] = useState(asset?.unit ?? DEFAULT_UNITS['gold']);
  const [purchasePrice, setPurchasePrice] = useState(asset?.purchase_price_egp.toString() ?? '');
  const [purchaseDate, setPurchaseDate] = useState(asset?.purchase_date ?? new Date().toISOString().slice(0, 10));
  const [currentValue, setCurrentValue] = useState(asset?.current_value_egp?.toString() ?? '');
  const [isGift, setIsGift] = useState(asset?.is_gift ?? false);
  const [notes, setNotes] = useState(asset?.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAuto = AUTO_PRICE_TYPES.has(assetType);

  const handleTypeChange = (t: AssetType) => {
    setAssetType(t);
    setUnit(DEFAULT_UNITS[t]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const qtyNum = parseFloat(quantity);
    const priceNum = isGift ? 0 : parseFloat(purchasePrice);
    const currentNum = currentValue.trim() ? parseFloat(currentValue) : null;

    if (!name.trim()) { setError('Name is required'); return; }
    if (isNaN(qtyNum) || qtyNum <= 0) { setError('Quantity must be a positive number'); return; }
    if (!isGift && (isNaN(priceNum) || priceNum < 0)) { setError('Purchase price must be 0 or more'); return; }

    setSaving(true);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { setError('Not authenticated'); setSaving(false); return; }

    const payload = {
      user_id: user.id,
      name: name.trim(),
      asset_type: assetType as string,
      quantity: qtyNum,
      unit: unit.trim() || DEFAULT_UNITS[assetType],
      purchase_price_egp: priceNum,
      purchase_date: purchaseDate,
      current_value_egp: isAuto ? null : currentNum,
      is_gift: isGift,
      notes: notes.trim() || null,
    };

    const { error: dbErr } = isEdit
      ? await (supabase.from as (t: string) => ReturnType<typeof supabase.from>)('assets')
          .update(payload)
          .eq('id', asset.id)
      : await (supabase.from as (t: string) => ReturnType<typeof supabase.from>)('assets')
          .insert(payload);

    if (dbErr) { setError(dbErr.message); setSaving(false); return; }
    onSaved();
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
      {/* Asset type */}
      <div>
        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">Asset Type</label>
        <div className="grid grid-cols-4 gap-2">
          {ASSET_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => handleTypeChange(t)}
              className={`flex flex-col items-center gap-1 rounded-lg border p-2 text-xs font-medium transition-colors ${
                assetType === t
                  ? 'border-brand-500 bg-brand-500/10 text-brand-500'
                  : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <span className="text-lg">{ASSET_TYPE_ICONS[t]}</span>
              <span>{ASSET_TYPE_LABELS[t]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Gift toggle */}
      <label className="flex items-center gap-3 cursor-pointer select-none">
        <div className="relative">
          <input
            type="checkbox"
            checked={isGift}
            onChange={(e) => setIsGift(e.target.checked)}
            className="sr-only"
          />
          <div className={`w-10 h-5 rounded-full transition-colors ${isGift ? 'bg-brand-500' : 'bg-gray-200 dark:bg-gray-700'}`} />
          <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${isGift ? 'translate-x-5' : ''}`} />
        </div>
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          🎁 This was a gift <span className="text-xs font-normal text-gray-400">(cost = EGP 0)</span>
        </span>
      </label>

      {/* Name */}
      <div>
        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Name / Description</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={assetType === 'gold' ? 'e.g. 21K Gold Bar' : assetType === 'car' ? 'e.g. Toyota Corolla 2022' : 'Asset name'}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>

      {/* Quantity + Unit */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Quantity</label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            min="0"
            step="any"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Unit</label>
          <input
            type="text"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="grams, sqm, units…"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      </div>

      {/* Purchase price + date */}
      <div className={`grid gap-3 ${isGift ? 'grid-cols-1' : 'grid-cols-2'}`}>
        {!isGift && (
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Purchase Price (EGP total)</label>
            <input
              type="number"
              value={purchasePrice}
              onChange={(e) => setPurchasePrice(e.target.value)}
              min="0"
              step="any"
              placeholder="0.00"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        )}
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            {isGift ? 'Date Received' : 'Purchase Date'}
          </label>
          <input
            type="date"
            value={purchaseDate}
            onChange={(e) => setPurchaseDate(e.target.value)}
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      </div>

      {/* Current value — only for non-auto types */}
      {!isAuto && (
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            Current Market Value (EGP) <span className="text-gray-400 font-normal">— optional, leave blank to use purchase price</span>
          </label>
          <input
            type="number"
            value={currentValue}
            onChange={(e) => setCurrentValue(e.target.value)}
            min="0"
            step="any"
            placeholder="0.00"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      )}

      {isAuto && (
        <p className="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950 rounded-lg px-3 py-2">
          Current value is calculated automatically using live {ASSET_TYPE_LABELS[assetType]} prices.
        </p>
      )}

      {/* Notes */}
      <div>
        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Notes <span className="font-normal text-gray-400">— optional</span></label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Any details…"
          className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={saving} className="flex-1">
          {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Asset'}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
