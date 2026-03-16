import { Card, CardHeader, CardBody } from '@/components/ui/card';
import type { ForecastPoint } from '@/lib/types';

interface ForecastChartProps {
  forecasts: ForecastPoint[];
}

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function formatEGP(amount: number): string {
  if (Math.abs(amount) >= 1000) {
    return `EGP ${(amount / 1000).toFixed(1)}k`;
  }
  return `EGP ${amount.toFixed(0)}`;
}

export function ForecastChart({ forecasts }: ForecastChartProps) {
  if (forecasts.length === 0) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">
            No forecast data available.
          </p>
        </CardBody>
      </Card>
    );
  }

  // Find the max value to scale bars
  const allValues = forecasts.flatMap((f) => [
    f.projected_income,
    f.projected_expenses,
    Math.abs(f.projected_net),
  ]);
  const maxValue = Math.max(...allValues, 1);

  const BAR_MAX_HEIGHT_PX = 140;

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          3-Month Forecast
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          Projected income, expenses, and net cash flow
        </p>
      </CardHeader>
      <CardBody>
        {/* Legend */}
        <div className="flex items-center gap-5 mb-6">
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm bg-green-500 inline-block" />
            <span className="text-xs text-gray-500 dark:text-gray-400">Income</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm bg-red-400 inline-block" />
            <span className="text-xs text-gray-500 dark:text-gray-400">Expenses</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm bg-blue-500 inline-block" />
            <span className="text-xs text-gray-500 dark:text-gray-400">Net</span>
          </div>
        </div>

        {/* Chart */}
        <div className="flex items-end gap-6 justify-around" style={{ height: BAR_MAX_HEIGHT_PX + 40 }}>
          {forecasts.map((point) => {
            const incomeH = Math.round((point.projected_income / maxValue) * BAR_MAX_HEIGHT_PX);
            const expenseH = Math.round((point.projected_expenses / maxValue) * BAR_MAX_HEIGHT_PX);
            const netAbs = Math.abs(point.projected_net);
            const netH = Math.round((netAbs / maxValue) * BAR_MAX_HEIGHT_PX);
            const netPositive = point.projected_net >= 0;
            const monthLabel = MONTH_ABBR[(point.month - 1) % 12];

            return (
              <div key={`${point.year}-${point.month}`} className="flex flex-col items-center gap-2 flex-1">
                {/* Bars */}
                <div
                  className="flex items-end gap-1 w-full justify-center"
                  style={{ height: BAR_MAX_HEIGHT_PX }}
                >
                  {/* Income bar */}
                  <div
                    className="w-5 sm:w-7 rounded-t-sm bg-green-500"
                    style={{ height: incomeH }}
                    title={`Income: ${formatEGP(point.projected_income)}`}
                    role="img"
                    aria-label={`${monthLabel} income: ${formatEGP(point.projected_income)}`}
                  />
                  {/* Expenses bar */}
                  <div
                    className="w-5 sm:w-7 rounded-t-sm bg-red-400"
                    style={{ height: expenseH }}
                    title={`Expenses: ${formatEGP(point.projected_expenses)}`}
                    role="img"
                    aria-label={`${monthLabel} expenses: ${formatEGP(point.projected_expenses)}`}
                  />
                  {/* Net bar */}
                  <div
                    className={`w-5 sm:w-7 rounded-t-sm ${netPositive ? 'bg-blue-500' : 'bg-blue-300'}`}
                    style={{ height: netH }}
                    title={`Net: ${formatEGP(point.projected_net)}`}
                    role="img"
                    aria-label={`${monthLabel} net: ${formatEGP(point.projected_net)}`}
                  />
                </div>

                {/* Month label */}
                <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">
                  {monthLabel} {point.year}
                </span>

                {/* Net value */}
                <span
                  className={`text-xs font-semibold tabular-nums ${
                    netPositive
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-red-500 dark:text-red-400'
                  }`}
                >
                  {netPositive ? '+' : '-'}{formatEGP(netAbs)}
                </span>
              </div>
            );
          })}
        </div>
      </CardBody>
    </Card>
  );
}
