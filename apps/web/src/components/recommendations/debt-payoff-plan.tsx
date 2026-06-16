import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { DebtOptimizationReportResponse } from '@/lib/api-client';

interface DebtPayoffPlanProps {
  report: DebtOptimizationReportResponse;
}

interface PayoffOrderEntry {
  debtId: string;
  name: string;
  outstandingBalance: number;
  payoffMonth: number | null;
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.round(amount));
}

/**
 * Derive the order in which debts are paid off under the snowball strategy by
 * finding, for each debt, the first month its `remaining_balance` reaches
 * zero in `monthly_steps`. Debts that never reach zero within the simulation
 * window sort last (in their original order).
 */
function derivePayoffOrder(report: DebtOptimizationReportResponse): PayoffOrderEntry[] {
  const { snowball, debts } = report;

  const payoffMonthByDebt = new Map<string, number>();
  for (const step of snowball.monthly_steps) {
    if (Number(step.remaining_balance) <= 0 && !payoffMonthByDebt.has(step.debt_id)) {
      payoffMonthByDebt.set(step.debt_id, step.month);
    }
  }

  const entries: PayoffOrderEntry[] = debts.map((debt) => ({
    debtId: debt.id,
    name: debt.name,
    outstandingBalance: Number(debt.outstanding_balance),
    payoffMonth: payoffMonthByDebt.get(debt.id) ?? null,
  }));

  return entries.sort((a, b) => {
    if (a.payoffMonth == null && b.payoffMonth == null) return 0;
    if (a.payoffMonth == null) return 1;
    if (b.payoffMonth == null) return -1;
    return a.payoffMonth - b.payoffMonth;
  });
}

export function DebtPayoffPlan({ report }: DebtPayoffPlanProps) {
  const { snowball, debts } = report;
  const totalBorrowed = debts.reduce((sum, debt) => sum + Number(debt.outstanding_balance), 0);
  const order = derivePayoffOrder(report);
  const monthlyBudget = Number(report.monthly_budget);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">
              Debt Payoff Plan
            </h2>
            <p className="mt-0.5 text-xs text-ink-muted">
              Snowball strategy — smallest balance first
            </p>
          </div>
          <Badge variant="info">{snowball.total_months} mo to debt-free</Badge>
        </div>
      </CardHeader>
      <CardBody>
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-surface-sunken p-3">
            <p className="text-xs text-ink-muted">Total borrowed</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-ink">
              EGP {formatEGP(totalBorrowed)}
            </p>
          </div>
          <div className="rounded-lg bg-surface-sunken p-3">
            <p className="text-xs text-ink-muted">Months to debt-free</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-ink">
              {snowball.total_months}
            </p>
          </div>
          <div className="rounded-lg bg-surface-sunken p-3">
            <p className="text-xs text-ink-muted">Modelled monthly budget</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-ink">
              EGP {formatEGP(monthlyBudget)}
            </p>
          </div>
        </div>

        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
          Payoff order
        </p>
        <ol className="space-y-2">
          {order.map((entry, idx) => (
            <li
              key={entry.debtId}
              className="flex items-center justify-between gap-3 rounded-lg border border-gray-100 px-3 py-2 border-line"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                  {idx + 1}
                </span>
                <span className="truncate text-sm font-medium text-ink">
                  {entry.name}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-3 text-right">
                <span className="text-xs tabular-nums text-ink-muted">
                  EGP {formatEGP(entry.outstandingBalance)}
                </span>
                <Badge variant={entry.payoffMonth != null ? 'success' : 'default'}>
                  {entry.payoffMonth != null ? `Month ${entry.payoffMonth}` : 'Beyond plan'}
                </Badge>
              </div>
            </li>
          ))}
        </ol>

        <p className="mt-4 text-xs leading-relaxed text-ink-muted">
          Since these are informal debts with no interest rate, the snowball order (paying off
          the smallest balance first) is the clearest path to becoming debt-free — there is no
          interest-cost tradeoff to weigh against it.
        </p>
      </CardBody>
    </Card>
  );
}
