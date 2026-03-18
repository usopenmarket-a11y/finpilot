import type { MonthlySpend } from '@/components/credit-cards/credit-card-tabs';

interface CreditCardSpendChartProps {
  data: MonthlySpend[];
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function CreditCardSpendChart({ data }: CreditCardSpendChartProps) {
  if (data.length === 0 || data.every((d) => d.total === 0)) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-gray-400 dark:text-gray-500">
        No spending data available
      </div>
    );
  }

  const maxVal = Math.max(...data.map((d) => d.total), 1);

  return (
    <div className="space-y-2">
      {data.map((entry) => {
        const pct = (entry.total / maxVal) * 100;
        const isHighest = entry.total === maxVal;
        return (
          <div key={entry.month}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-gray-600 dark:text-gray-400 w-20 flex-shrink-0">
                {entry.month}
              </span>
              <div className="flex-1 mx-3">
                <div className="h-5 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
                  <div
                    className={`h-full rounded transition-all duration-500 ${
                      isHighest
                        ? 'bg-indigo-500'
                        : 'bg-indigo-200 dark:bg-indigo-800'
                    }`}
                    style={{ width: `${pct}%` }}
                    role="progressbar"
                    aria-valuenow={entry.total}
                    aria-valuemin={0}
                    aria-valuemax={maxVal}
                    aria-label={`${entry.month}: EGP ${formatEGP(entry.total)}`}
                  />
                </div>
              </div>
              <span className="text-xs font-semibold tabular-nums text-gray-900 dark:text-white w-24 text-right flex-shrink-0">
                EGP {formatEGP(entry.total)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
