import type { Asset } from './types';
import { resolveCurrentValue, ASSET_TYPE_LABELS, ASSET_TYPE_ICONS } from './types';

function formatEGP(n: number) {
  return new Intl.NumberFormat('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}

interface AssetSummaryProps {
  assets: Asset[];
  livePrices: Record<string, number>;
}

export function AssetSummary({ assets, livePrices }: AssetSummaryProps) {
  const totalCost = assets.reduce((s, a) => s + a.purchase_price_egp, 0);
  const totalValue = assets.reduce((s, a) => s + resolveCurrentValue(a, livePrices), 0);
  const totalGain = totalValue - totalCost;
  const gainPct = totalCost > 0 ? (totalGain / totalCost) * 100 : 0;

  // Group by type for breakdown
  const byType = assets.reduce<Record<string, { value: number; count: number }>>((acc, a) => {
    const v = resolveCurrentValue(a, livePrices);
    acc[a.asset_type] = { value: (acc[a.asset_type]?.value ?? 0) + v, count: (acc[a.asset_type]?.count ?? 0) + 1 };
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Top KPIs */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Total Portfolio" value={`EGP ${formatEGP(totalValue)}`} valueColor="text-gray-900 dark:text-white" />
        <KpiCard label="Total Cost" value={`EGP ${formatEGP(totalCost)}`} valueColor="text-gray-500 dark:text-gray-400" />
        <KpiCard
          label="Total Gain / Loss"
          value={`${totalGain >= 0 ? '+' : ''}EGP ${formatEGP(totalGain)}`}
          valueColor={totalGain >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}
        />
        <KpiCard
          label="Return"
          value={`${gainPct >= 0 ? '+' : ''}${gainPct.toFixed(2)}%`}
          valueColor={gainPct >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}
        />
      </div>

      {/* Breakdown by type */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-3">Portfolio Breakdown</p>
        <div className="space-y-2">
          {Object.entries(byType)
            .sort((a, b) => b[1].value - a[1].value)
            .map(([type, { value, count }]) => {
              const pct = totalValue > 0 ? (value / totalValue) * 100 : 0;
              return (
                <div key={type}>
                  <div className="mb-1 flex flex-col gap-1 text-sm sm:flex-row sm:items-center sm:justify-between">
                    <span className="text-gray-700 dark:text-gray-300">
                      {ASSET_TYPE_ICONS[type as keyof typeof ASSET_TYPE_ICONS]} {ASSET_TYPE_LABELS[type as keyof typeof ASSET_TYPE_LABELS]} ({count})
                    </span>
                    <span className="font-semibold tabular-nums text-gray-900 dark:text-white sm:text-right">
                      EGP {formatEGP(value)} <span className="text-gray-400 font-normal">({pct.toFixed(1)}%)</span>
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                    <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

function KpiCard({ label, value, valueColor }: { label: string; value: string; valueColor: string }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
      <p className={`break-words text-base font-bold tabular-nums ${valueColor}`}>{value}</p>
    </div>
  );
}
