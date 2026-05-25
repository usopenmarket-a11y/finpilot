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
    setAssets((data ?? []) as Asset[]);
    setLoading(false);
  }, []);

  const fetchLivePrices = useCallback(async () => {
    setPriceLoading(true);
    setPriceError(null);
    try {
      // metals.live — free, no API key, returns USD prices per troy oz
      // XAU = gold, XAG = silver; 1 troy oz = 31.1035 grams
      // USD/EGP rate from frankfurter.app (free, no key)
      const [metalsRes, fxRes] = await Promise.all([
        fetch('https://metals.live/api/spot', { next: { revalidate: 3600 } }),
        fetch('https://api.frankfurter.app/latest?from=USD&to=EGP'),
      ]);

      if (!metalsRes.ok || !fxRes.ok) throw new Error('Price fetch failed');

      const metals = await metalsRes.json() as Array<{ gold?: number; silver?: number }>;
      const fx = await fxRes.json() as { rates: { EGP: number } };

      const usdEgp = fx.rates.EGP;
      const latestMetals = metals[0] ?? {};
      const TROY_OZ_TO_GRAM = 31.1035;

      const prices: Record<string, number> = {};
      if (latestMetals.gold) prices['gold'] = (latestMetals.gold / TROY_OZ_TO_GRAM) * usdEgp;
      if (latestMetals.silver) prices['silver'] = (latestMetals.silver / TROY_OZ_TO_GRAM) * usdEgp;

      setLivePrices(prices);
      setPriceUpdatedAt(new Date());
    } catch {
      setPriceError('Could not fetch live prices. Showing manual values.');
    } finally {
      setPriceLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAssets();
    void fetchLivePrices();
  }, [fetchAssets, fetchLivePrices]);

  const handleSaved = () => {
    setShowAddForm(false);
    setEditTarget(null);
    void fetchAssets();
  };

  const handleDelete = async (id: string) => {
    const supabase = createClient();
    await supabase.from('assets').delete().eq('id', id);
    setAssets((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Assets</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Track your physical and financial assets
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void fetchLivePrices()}
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
