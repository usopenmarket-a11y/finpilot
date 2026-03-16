import { MonthlyPlanCard } from '@/components/recommendations/monthly-plan-card';
import { SavingsOpportunities } from '@/components/recommendations/savings-opportunities';
import { ForecastChart } from '@/components/recommendations/forecast-chart';
import type { MonthlyPlan, SavingsOpportunity, ForecastPoint } from '@/lib/types';

const MOCK_PLAN: MonthlyPlan = {
  month: 3,
  year: 2026,
  summary:
    'Your spending is well-controlled this month with a healthy savings rate of 77%. Focus on reducing cash withdrawals and optimising your entertainment subscriptions to push your health score above 80.',
  projected_savings: 14301,
  health_score: 74,
  action_items: [
    {
      priority: 'high',
      category: 'Cash Flow',
      title: 'Reduce ATM withdrawals',
      description:
        'You withdrew EGP 2,000 in cash this month. Using card payments where possible improves tracking and often earns cashback rewards.',
      estimated_impact: 500,
    },
    {
      priority: 'medium',
      category: 'Subscriptions',
      title: 'Audit recurring subscriptions',
      description:
        'You have 2 active entertainment subscriptions totalling EGP 499/mo. Review if both are being fully utilised.',
      estimated_impact: 149,
    },
    {
      priority: 'low',
      category: 'Dining',
      title: 'Meal-prep 2 days a week',
      description:
        'Preparing meals at home twice a week could reduce your food & dining spend by approximately 15%.',
      estimated_impact: 127,
    },
  ],
};

const MOCK_OPPORTUNITIES: SavingsOpportunity[] = [
  {
    opportunity_type: 'recurring',
    title: 'Duplicate Streaming Subscriptions',
    description:
      'You appear to have both Netflix and another streaming service active. Consider consolidating.',
    estimated_monthly_saving: 149,
  },
  {
    opportunity_type: 'fee',
    title: 'ATM Withdrawal Fees',
    description:
      'Frequent out-of-network ATM usage is incurring avoidable fees. Switch to in-network ATMs or use card payments.',
    estimated_monthly_saving: 80,
  },
  {
    opportunity_type: 'spike',
    title: 'Shopping Spend Spike',
    description:
      'Your shopping spend was 35% above your 3-month average this month.',
    estimated_monthly_saving: 220,
  },
];

const MOCK_FORECAST: ForecastPoint[] = [
  { year: 2026, month: 3, projected_income: 18500, projected_expenses: 4199, projected_net: 14301 },
  { year: 2026, month: 4, projected_income: 18500, projected_expenses: 4050, projected_net: 14450 },
  { year: 2026, month: 5, projected_income: 18500, projected_expenses: 3900, projected_net: 14600 },
];

export default function RecommendationsPage() {
  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Recommendations</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          AI-powered insights to improve your financial health
        </p>
      </div>

      {/* Two-column layout on large screens */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        {/* Left: monthly plan */}
        <div className="space-y-6">
          <MonthlyPlanCard plan={MOCK_PLAN} />
        </div>

        {/* Right: opportunities + forecast */}
        <div className="space-y-6">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-3">
              Savings Opportunities
            </h2>
            <SavingsOpportunities opportunities={MOCK_OPPORTUNITIES} />
          </div>
          <ForecastChart forecasts={MOCK_FORECAST} />
        </div>
      </div>
    </div>
  );
}
