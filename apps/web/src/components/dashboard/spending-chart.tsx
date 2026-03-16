import { Card, CardHeader, CardBody } from '@/components/ui/card';

interface SpendingCategory {
  name: string;
  amount: number;
  color: string;
}

interface SpendingChartProps {
  categories: SpendingCategory[];
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function SpendingChart({ categories }: SpendingChartProps) {
  const total = categories.reduce((sum, c) => sum + c.amount, 0);

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          Spending Breakdown
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          Current month — EGP {formatEGP(total)} total
        </p>
      </CardHeader>
      <CardBody>
        <div className="space-y-3">
          {categories.map((cat) => {
            const pct = total > 0 ? (cat.amount / total) * 100 : 0;
            return (
              <div key={cat.name}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: cat.color }}
                      aria-hidden="true"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{cat.name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
                      {pct.toFixed(1)}%
                    </span>
                    <span className="text-sm font-medium text-gray-900 dark:text-white tabular-nums">
                      EGP {formatEGP(cat.amount)}
                    </span>
                  </div>
                </div>
                <div className="h-2 w-full bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: cat.color }}
                    role="progressbar"
                    aria-valuenow={pct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${cat.name}: ${pct.toFixed(1)}%`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </CardBody>
    </Card>
  );
}
