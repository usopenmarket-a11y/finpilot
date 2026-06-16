import { Badge } from '@/components/ui/badge';
import type { Asset } from './types';
import { resolveCurrentValue, gainLoss, gainLossPct, ASSET_TYPE_LABELS, ASSET_TYPE_ICONS, AUTO_PRICE_TYPES } from './types';

function formatEGP(n: number) {
  return new Intl.NumberFormat('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}

function formatDate(d: string) {
  return new Intl.DateTimeFormat('en-EG', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(d));
}

interface AssetListProps {
  assets: Asset[];
  loading: boolean;
  livePrices: Record<string, number>;
  onEdit: (asset: Asset) => void;
  onDelete: (id: string) => void;
}

export function AssetList({ assets, loading, livePrices, onEdit, onDelete }: AssetListProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-line bg-surface p-8 text-center text-sm text-gray-400">
        Loading assets…
      </div>
    );
  }

  if (assets.length === 0) {
    return (
      <div className="rounded-xl border border-line bg-surface py-16 text-center">
        <p className="text-5xl mb-4">📦</p>
        <p className="text-base font-medium text-ink mb-1">No assets yet</p>
        <p className="text-sm text-ink-muted">Add your first asset to start tracking your portfolio.</p>
      </div>
    );
  }

  // Group by asset type
  const grouped = assets.reduce<Record<string, Asset[]>>((acc, a) => {
    (acc[a.asset_type] ??= []).push(a);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(grouped).map(([type, group]) => (
        <div key={type}>
          <h2 className="text-sm font-semibold text-ink-muted uppercase tracking-wide mb-3">
            {ASSET_TYPE_ICONS[type as keyof typeof ASSET_TYPE_ICONS]} {ASSET_TYPE_LABELS[type as keyof typeof ASSET_TYPE_LABELS]}
          </h2>
          <div className="rounded-xl border border-line bg-surface divide-y divide-gray-100 dark:divide-gray-800">
            {group.map((asset) => {
              const currentValue = resolveCurrentValue(asset, livePrices);
              const gl = gainLoss(asset, livePrices);
              const glPct = gainLossPct(asset, livePrices);
              const isAutoPrice = AUTO_PRICE_TYPES.has(asset.asset_type) && !!livePrices[asset.asset_type];

              return (
                <div key={asset.id} className="px-4 py-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-ink">{asset.name}</span>
                        {asset.is_gift && <Badge variant="warning">🎁 Gift</Badge>}
                        {isAutoPrice && <Badge variant="default">Live price</Badge>}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1 text-xs text-ink-faint">
                        <span>{asset.quantity} {asset.unit}</span>
                        {asset.asset_type === 'foreign_currency' && asset.currency_code && (() => {
                          const rate = livePrices[asset.currency_code!];
                          return rate ? <span>@ EGP {rate.toFixed(2)}/{asset.currency_code}</span> : null;
                        })()}
                        <span>{asset.is_gift ? 'Received' : 'Bought'} {formatDate(asset.purchase_date)}</span>
                        {!asset.is_gift && <span>Cost EGP {formatEGP(asset.purchase_price_egp)}</span>}
                      </div>
                      {asset.notes && (
                        <p className="text-xs text-ink-faint mt-1 truncate">{asset.notes}</p>
                      )}
                    </div>

                    <div className="flex-shrink-0 sm:text-right">
                      <p className="text-sm font-bold tabular-nums text-ink">
                        EGP {formatEGP(currentValue)}
                      </p>
                      {glPct !== null ? (
                        <p className={`text-xs font-semibold tabular-nums ${gl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                          {gl >= 0 ? '+' : ''}{formatEGP(gl)} ({glPct >= 0 ? '+' : ''}{glPct.toFixed(1)}%)
                        </p>
                      ) : (
                        <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                          🎁 gift · no cost basis
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex gap-3 mt-3">
                    <button
                      onClick={() => onEdit(asset)}
                      className="text-xs text-accent hover:text-brand-600 font-medium"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete "${asset.name}"?`)) onDelete(asset.id);
                      }}
                      className="text-xs text-red-500 hover:text-red-600 font-medium"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
