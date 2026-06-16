import { Card, CardBody } from '@/components/ui/card';
import { HealthScore } from '@/components/dashboard/health-score';
import type { MonthlyPlan } from '@/lib/types';

interface MonthlyPlanCardProps {
  plan: MonthlyPlan;
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * Financial Health hero — the real continuous health score (0-100), a
 * plain-language summary, and the projected monthly savings. Action items
 * are intentionally NOT rendered here; they flow into the
 * `ActionFeed` component to avoid double-rendering.
 */
export function MonthlyPlanCard({ plan }: MonthlyPlanCardProps) {
  const monthName = MONTH_NAMES[(plan.month - 1) % 12];

  return (
    <div className="flex flex-col gap-6">
      {/* Health score */}
      <HealthScore score={plan.health_score} />

      {/* Summary */}
      <Card>
        <CardBody>
          <div className="mb-3 flex items-start justify-between">
            <div>
              <h2 className="text-base font-semibold text-ink">
                {monthName} {plan.year} Summary
              </h2>
              <p className="text-xs text-ink-muted mt-0.5">
                Projected savings:{' '}
                <span className="text-accent font-semibold font-mono tabular-nums">
                  EGP {formatEGP(plan.projected_savings)}
                </span>
              </p>
            </div>
          </div>
          <p className="text-sm text-ink-muted leading-relaxed">
            {plan.summary}
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
