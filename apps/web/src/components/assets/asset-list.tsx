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
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center text-sm text-gray-400">
        Loading assets…
      </div>
    );
  }

  if (assets.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 py-16 text-center">
        <p className="text-5xl mb-4">📦</p>
        <p className="text-base font-medium text-gray-900 dark:text-white mb-1">No assets yet</p>
        <p className="text-sm text-gray-500 dark:text-gray-400">Add your first asset to start tracking your portfolio.</p>
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
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
            {ASSET_TYPE_ICONS[type as keyof typeof ASSET_TYPE_ICONS]} {ASSET_TYPE_LABELS[type as keyof typeof ASSET_TYPE_LABELS]}
          </h2>
          <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 divide-y divide-gray-100 dark:divide-gray-800">
            {group.map((asset) => {
              const currentValue = resolveCurrentValue(asset, livePrices);
              const gl = gainLoss(asset, livePrices);
              const glPct = gainLossPct(asset, livePrices);
              const isAutoPrice = AUTO_PRICE_TYPES.has(asset.asset_type) && !!livePrices[asset.asset_type];

              return (
                <div key={asset.id} className="px-4 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{asset.name}</span>
                        {asset.is_gift && <Badge variant="warning">🎁 Gift</Badge>}
                        {isAutoPrice && <Badge variant="default">Live price</Badge>}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1 text-xs text-gray-400 dark:text-gray-500">
                        <span>{asset.quantity} {asset.unit}</span>
                        <span>{asset.is_gift ? 'Received' : 'Bought'} {formatDate(asset.purchase_date)}</span>
                        {!asset.is_gift && <span>Cost EGP {formatEGP(asset.purchase_price_egp)}</span>}
                      </div>
                      {asset.notes && (
                        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1 truncate">{asset.notes}</p>
                      )}
                    </div>

                    <div className="flex-shrink-0 text-right">
                      <p className="text-sm font-bold tabular-nums text-gray-900 dark:text-white">
                        EGP {formatEGP(currentValue)}
                      </p>
                      <p className={`text-xs font-semibold tabular-nums ${gl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                        {gl >= 0 ? '+' : ''}{formatEGP(gl)}{glPct !== null ? ` (${glPct >= 0 ? '+' : ''}${glPct.toFixed(1)}%)` : ' (gift)'}
                      </p>
                    </div>
                  </div>

                  <div className="flex gap-3 mt-3">
                    <button
                      onClick={() => onEdit(asset)}
                      className="text-xs text-brand-500 hover:text-brand-600 font-medium"
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
