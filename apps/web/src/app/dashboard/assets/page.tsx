'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import { AssetList } from '@/components/assets/asset-list';
import { AssetForm } from '@/components/assets/asset-form';
import { AssetSummary } from '@/components/assets/asset-summary';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import type { Asset } from '@/components/assets/types';

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editTarget, setEditTarget] = useState<Asset | null>(null);
  // livePrice: EGP per gram for gold/silver, fetched from metals API
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [priceLoading, setPriceLoading] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [priceUpdatedAt, setPriceUpdatedAt] = useState<Date | null>(null);

  const fetchAssets = useCallback(async () => {
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { setLoading(false); return; }
    const { data } = await supabase
      .from('assets')
      .select('*')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false });
    const fetched = (data ?? []) as Asset[];
    setAssets(fetched);
    setLoading(false);
    return fetched;
  }, []);

  const fetchLivePrices = useCallback(async (currentAssets: Asset[]) => {
    setPriceLoading(true);
    setPriceError(null);
    try {
      const fxCurrencies = [...new Set(
        currentAssets
          .filter((a) => a.asset_type === 'foreign_currency' && a.currency_code)
          .map((a) => a.currency_code as string)
      )];

      const needsMetals = currentAssets.some(
        (a) => a.asset_type === 'gold' || a.asset_type === 'silver',
      );

      // FX rates: open.er-api.com is free, no API key, EGP-based. rates[code]
      // is the value of 1 EGP in `code`, so we invert to get EGP per 1 unit.
      // Metals: gold-api.com is free, no key, returns USD per troy ounce.
      // Both are fetched independently so one failing doesn't block the other.
      const [fxRes, goldRes, silverRes] = await Promise.all([
        fetch('https://open.er-api.com/v6/latest/EGP'),
        needsMetals
          ? fetch('https://api.gold-api.com/price/XAU').then((r) => (r.ok ? r.json() : null)).catch(() => null)
          : Promise.resolve(null),
        needsMetals
          ? fetch('https://api.gold-api.com/price/XAG').then((r) => (r.ok ? r.json() : null)).catch(() => null)
          : Promise.resolve(null),
      ]);

      if (!fxRes.ok) throw new Error('FX rate fetch failed');

      const fxData = await fxRes.json() as {
        result?: string;
        rates: Record<string, number>;
      };
      if (fxData.result === 'error' || !fxData.rates) throw new Error('FX rate fetch failed');

      const prices: Record<string, number> = {};

      // Gold + silver: convert USD/oz -> EGP/gram using the live USD rate.
      const usdPerEgp = fxData.rates['USD'];
      const egpPerUsd = usdPerEgp ? 1 / usdPerEgp : 0;
      const TROY_OZ_TO_GRAM = 31.1035;
      const goldData = goldRes as { price?: number } | null;
      const silverData = silverRes as { price?: number } | null;
      if (goldData?.price && egpPerUsd) {
        prices['gold'] = (goldData.price / TROY_OZ_TO_GRAM) * egpPerUsd;
      }
      if (silverData?.price && egpPerUsd) {
        prices['silver'] = (silverData.price / TROY_OZ_TO_GRAM) * egpPerUsd;
      }

      // Foreign currencies — invert EGP-base rates to get EGP per 1 unit.
      for (const code of fxCurrencies) {
        const ratePerEgp = fxData.rates[code];
        if (ratePerEgp) prices[code] = 1 / ratePerEgp;
      }

      setLivePrices(prices);
      setPriceUpdatedAt(new Date());
    } catch {
      setPriceError('Could not fetch live prices. Showing manual values.');
    } finally {
      setPriceLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAssets().then((fetched) => {
      void fetchLivePrices(fetched ?? []);
    });
  }, [fetchAssets, fetchLivePrices]);

  const handleSaved = () => {
    setShowAddForm(false);
    setEditTarget(null);
    void fetchAssets().then((fetched) => {
      void fetchLivePrices(fetched ?? []);
    });
  };

  const handleDelete = async (id: string) => {
    const supabase = createClient();
    await supabase.from('assets').delete().eq('id', id);
    setAssets((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Assets</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Track your physical and financial assets
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void fetchLivePrices(assets)}
            disabled={priceLoading}
          >
            {priceLoading ? 'Refreshing…' : 'Refresh Prices'}
          </Button>
          <Button onClick={() => setShowAddForm(true)}>+ Add Asset</Button>
        </div>
      </div>

      {/* Live price status */}
      {priceError && (
        <p className="text-xs text-yellow-600 dark:text-yellow-400">{priceError}</p>
      )}
      {priceUpdatedAt && !priceError && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Prices updated {priceUpdatedAt.toLocaleTimeString('en-EG')}
          {livePrices['gold'] ? ` · Gold EGP ${livePrices['gold'].toFixed(2)}/g` : ''}
          {livePrices['silver'] ? ` · Silver EGP ${livePrices['silver'].toFixed(2)}/g` : ''}
          {Object.entries(livePrices)
            .filter(([k]) => !['gold', 'silver'].includes(k))
            .map(([code, rate]) => ` · ${code}/EGP ${rate.toFixed(2)}`)
            .join('')}
        </p>
      )}

      {/* Summary cards */}
      {!loading && assets.length > 0 && (
        <AssetSummary assets={assets} livePrices={livePrices} />
      )}

      {/* Asset list */}
      <AssetList
        assets={assets}
        loading={loading}
        livePrices={livePrices}
        onEdit={setEditTarget}
        onDelete={handleDelete}
      />

      {/* Add modal */}
      <Modal open={showAddForm} title="Add Asset" onClose={() => setShowAddForm(false)}>
        <AssetForm onSaved={handleSaved} onCancel={() => setShowAddForm(false)} />
      </Modal>

      <Modal open={!!editTarget} title="Edit Asset" onClose={() => setEditTarget(null)}>
        {editTarget && (
          <AssetForm
            asset={editTarget}
            onSaved={handleSaved}
            onCancel={() => setEditTarget(null)}
          />
        )}
      </Modal>
    </div>
  );
}
