import { Card, CardBody } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { HealthScore } from '@/components/dashboard/health-score';
import type { MonthlyPlan, ActionItem } from '@/lib/types';

interface MonthlyPlanCardProps {
  plan: MonthlyPlan;
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function priorityVariant(priority: ActionItem['priority']): 'danger' | 'warning' | 'info' {
  switch (priority) {
    case 'high':
      return 'danger';
    case 'medium':
      return 'warning';
    case 'low':
      return 'info';
  }
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function ActionItemRow({ item }: { item: ActionItem }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-100 dark:border-gray-800 last:border-0">
      <div className="flex-shrink-0 mt-0.5">
        <Badge variant={priorityVariant(item.priority)}>
          {item.priority.charAt(0).toUpperCase() + item.priority.slice(1)}
        </Badge>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white">{item.title}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-relaxed">
          {item.description}
        </p>
        <p className="text-xs text-brand-500 font-medium mt-1">
          Est. impact: EGP {formatEGP(item.estimated_impact)}/mo
        </p>
      </div>
    </div>
  );
}

export function MonthlyPlanCard({ plan }: MonthlyPlanCardProps) {
  const monthName = MONTH_NAMES[(plan.month - 1) % 12];

  return (
    <div className="flex flex-col gap-6">
      {/* Health score */}
      <HealthScore score={plan.health_score} />

      {/* Summary */}
      <Card>
        <CardBody>
          <div className="flex items-start justify-between mb-3">
            <div>
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">
                {monthName} {plan.year} Plan
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                Projected savings: {' '}
                <span className="text-brand-500 font-semibold">
                  EGP {formatEGP(plan.projected_savings)}
                </span>
              </p>
            </div>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed mb-4">
            {plan.summary}
          </p>

          {/* Action items */}
          {plan.action_items.length > 0 ? (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                Action Items ({plan.action_items.length})
              </p>
              <div>
                {plan.action_items.map((item, idx) => (
                  <ActionItemRow key={idx} item={item} />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
              No action items for this period.
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
