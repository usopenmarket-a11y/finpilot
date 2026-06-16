export const dynamic = 'force-dynamic';

import Link from 'next/link';
import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { MonthlyPlanCard } from '@/components/recommendations/monthly-plan-card';
import { ActionFeed } from '@/components/recommendations/action-feed';
import { ForecastChart } from '@/components/recommendations/forecast-chart';
import { DebtPayoffPlan } from '@/components/recommendations/debt-payoff-plan';
import {
  getMonthlyPlan,
  getCashFlowForecast,
  getSavingsReport,
  getDebtPayoffPlan,
  type MonthlyPlanResponse,
  type CashFlowForecastResponse,
  type SavingsReportResponse,
  type DebtOptimizationReportResponse,
  type SpendingBreakdownInput,
  type CategoryBreakdownInput,
  type TrendReportInput,
  type MonthlyPointInput,
  type TransactionSummaryInput,
  type DebtItemInput,
} from '@/lib/api-client';
import type { MonthlyPlan, SavingsOpportunity, ForecastPoint, ActionItem } from '@/lib/types';
import type { Database } from '@finpilot/shared';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];
type DebtRow = Database['public']['Tables']['debts']['Row'];

// ---------------------------------------------------------------------------
// Helpers (mirrors apps/web/src/app/dashboard/page.tsx)
// ---------------------------------------------------------------------------

function parseAmount(value: number | string | null | undefined): number {
  const amount = typeof value === 'number' ? value : parseFloat(String(value ?? 0));
  return Number.isFinite(amount) ? amount : 0;
}

function dateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function isInRange(date: string, start: string, end: string): boolean {
  return date >= start && date <= end;
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.round(amount));
}

// ---------------------------------------------------------------------------
// Wire-format input builders
// ---------------------------------------------------------------------------

/**
 * Build a SpendingBreakdownInput from the current calendar month's
 * non-credit-card transactions.
 */
function buildSpendingBreakdown(
  transactions: TransactionRow[],
  ccAccountIds: Set<string>,
  monthStart: string,
  monthEnd: string,
): SpendingBreakdownInput {
  let totalDebits = 0;
  let totalCredits = 0;
  const categoryTotals = new Map<string, { total: number; count: number }>();

  for (const tx of transactions) {
    if (ccAccountIds.has(tx.account_id)) continue;
    if (!isInRange(tx.transaction_date, monthStart, monthEnd)) continue;

    const amount = parseAmount(tx.amount);

    if (tx.transaction_type === 'debit') {
      totalDebits += amount;
      const category = tx.category ?? 'Uncategorized';
      const existing = categoryTotals.get(category) ?? { total: 0, count: 0 };
      existing.total += amount;
      existing.count += 1;
      categoryTotals.set(category, existing);
    } else if (tx.transaction_type === 'credit') {
      totalCredits += amount;
    }
  }

  const byCategory: CategoryBreakdownInput[] = Array.from(categoryTotals.entries()).map(
    ([category, { total, count }]) => ({
      category,
      total,
      transaction_count: count,
      percentage: totalDebits > 0 ? (total / totalDebits) * 100 : 0,
    }),
  );

  return {
    total_debits: totalDebits,
    total_credits: totalCredits,
    net: totalCredits - totalDebits,
    by_category: byCategory,
  };
}

/**
 * Build a TrendReportInput from a 6-month lookback of non-credit-card
 * transactions (oldest first, ending with the current calendar month).
 */
function buildTrendReport(
  transactions: TransactionRow[],
  ccAccountIds: Set<string>,
  today: Date,
): TrendReportInput {
  const monthlyPoints: MonthlyPointInput[] = [];

  for (let offset = 5; offset >= 0; offset -= 1) {
    const monthDate = new Date(today.getFullYear(), today.getMonth() - offset, 1);
    const start = dateKey(monthDate);
    const end = dateKey(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0));

    let totalDebits = 0;
    let totalCredits = 0;
    let transactionCount = 0;

    for (const tx of transactions) {
      if (ccAccountIds.has(tx.account_id)) continue;
      if (!isInRange(tx.transaction_date, start, end)) continue;

      transactionCount += 1;
      const amount = parseAmount(tx.amount);
      if (tx.transaction_type === 'debit') {
        totalDebits += amount;
      } else if (tx.transaction_type === 'credit') {
        totalCredits += amount;
      }
    }

    monthlyPoints.push({
      year: monthDate.getFullYear(),
      month: monthDate.getMonth() + 1,
      total_debits: totalDebits,
      total_credits: totalCredits,
      net: totalCredits - totalDebits,
      transaction_count: transactionCount,
    });
  }

  const avgMonthlySpend =
    monthlyPoints.reduce((sum, point) => sum + point.total_debits, 0) / monthlyPoints.length;
  const avgMonthlyIncome =
    monthlyPoints.reduce((sum, point) => sum + point.total_credits, 0) / monthlyPoints.length;

  // spend_trend_direction: compare the most recent month's debits to the
  // average of the prior months' debits.
  const mostRecentDebits = monthlyPoints[monthlyPoints.length - 1]?.total_debits ?? 0;
  const priorPoints = monthlyPoints.slice(0, -1);
  const priorAvgSpend =
    priorPoints.length > 0
      ? priorPoints.reduce((sum, point) => sum + point.total_debits, 0) / priorPoints.length
      : 0;

  let spendTrendDirection: 'up' | 'down' | 'flat' = 'flat';
  if (priorAvgSpend > 0) {
    const change = (mostRecentDebits - priorAvgSpend) / priorAvgSpend;
    if (change > 0.05) spendTrendDirection = 'up';
    else if (change < -0.05) spendTrendDirection = 'down';
  }

  return {
    lookback_months: 6,
    monthly_points: monthlyPoints,
    avg_monthly_spend: avgMonthlySpend,
    avg_monthly_income: avgMonthlyIncome,
    spend_trend_direction: spendTrendDirection,
  };
}

/**
 * Build TransactionSummaryInput[] from all fetched transactions, filtering
 * out rows that would fail backend validation (amount must be > 0,
 * description must be non-empty).
 */
function buildTransactionSummaries(transactions: TransactionRow[]): TransactionSummaryInput[] {
  const summaries: TransactionSummaryInput[] = [];

  for (const tx of transactions) {
    const amount = parseAmount(tx.amount);
    const description = tx.description?.trim() ?? '';
    if (amount <= 0 || description.length === 0) continue;

    summaries.push({
      description,
      amount,
      transaction_type: tx.transaction_type as 'debit' | 'credit',
      transaction_date: tx.transaction_date,
      category: tx.category,
    });
  }

  return summaries;
}

/**
 * Build DebtItemInput[] from active/partial borrowed debts. No interest rate
 * or minimum payment data exists for these informal debts, so both are 0.
 */
function buildDebtItems(debts: DebtRow[]): DebtItemInput[] {
  return debts
    .filter((debt) => debt.debt_type === 'borrowed' && (debt.status === 'active' || debt.status === 'partial'))
    .map((debt) => ({
      id: debt.id,
      name: debt.counterparty_name,
      debt_type: 'borrowed' as const,
      outstanding_balance: parseAmount(debt.outstanding_balance),
      interest_rate: 0,
      minimum_payment: 0,
      currency: debt.currency,
    }));
}

// ---------------------------------------------------------------------------
// Response mappers (wire response -> @/lib/types)
// ---------------------------------------------------------------------------

function mapMonthlyPlan(response: MonthlyPlanResponse): MonthlyPlan {
  return {
    month: response.month,
    year: response.year,
    summary: response.summary,
    projected_savings: Number(response.projected_savings),
    health_score: Math.round(Math.max(0, Math.min(1, response.health_score)) * 100),
    action_items: response.action_items.map(
      (item): ActionItem => ({
        priority: item.priority,
        category: item.category,
        title: item.title,
        description: item.description,
        estimated_impact: Number(item.estimated_impact),
      }),
    ),
  };
}

function mapSavingsOpportunities(response: SavingsReportResponse): SavingsOpportunity[] {
  return response.opportunities.map((opp) => ({
    opportunity_type: opp.opportunity_type,
    title: opp.title,
    description: opp.description,
    estimated_monthly_saving: Number(opp.estimated_monthly_saving),
    transactions: opp.transactions,
  }));
}

function mapForecastPoints(response: CashFlowForecastResponse): ForecastPoint[] {
  return response.forecast_points.map((point) => ({
    year: point.year,
    month: point.month,
    projected_income: Number(point.projected_income),
    projected_expenses: Number(point.projected_expenses),
    projected_net: Number(point.projected_net),
  }));
}

// ---------------------------------------------------------------------------
// Small presentational helpers for section fallbacks / empty states
// ---------------------------------------------------------------------------

function SectionError({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-ink">{title}</h2>
      </CardHeader>
      <CardBody>
        <p className="py-4 text-center text-sm text-ink-muted">
          Unable to load — try refreshing the page.
        </p>
      </CardBody>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card>
      <CardBody>
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <p className="text-base font-semibold text-ink">
            No transactions yet
          </p>
          <p className="max-w-sm text-sm text-ink-muted">
            Connect a bank account in Settings to get personalised recommendations based on your
            real spending.
          </p>
          <Link
            href="/dashboard/settings"
            className="mt-2 inline-flex items-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
          >
            Go to Settings
          </Link>
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page (Server Component)
// ---------------------------------------------------------------------------

export default async function RecommendationsPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [accountsResult, transactionsResult, debtsResult, sessionResult] = await Promise.all([
    supabase
      .from('bank_accounts')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true),
    supabase
      .from('transactions')
      .select('*')
      .eq('user_id', userId)
      .order('transaction_date', { ascending: false })
      .limit(5000),
    supabase
      .from('debts')
      .select('*')
      .eq('user_id', userId)
      .in('status', ['active', 'partial']),
    supabase.auth.getSession(),
  ]);

  const accounts: BankAccountRow[] = accountsResult.data ?? [];
  const allTransactions: TransactionRow[] = transactionsResult.data ?? [];
  const debts: DebtRow[] = debtsResult.data ?? [];
  const accessToken = sessionResult.data.session?.access_token;

  const header = (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight text-ink">Recommendations</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Personalised insights to improve your financial health
      </p>
    </div>
  );

  // -------------------------------------------------------------------------
  // Empty state — no transactions, skip all backend calls.
  // -------------------------------------------------------------------------
  if (allTransactions.length === 0) {
    return (
      <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
        {header}
        <EmptyState />
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Build wire-format inputs
  // -------------------------------------------------------------------------

  const today = new Date();
  const monthStart = dateKey(new Date(today.getFullYear(), today.getMonth(), 1));
  const monthEnd = dateKey(new Date(today.getFullYear(), today.getMonth() + 1, 0));

  const creditCardAccounts = accounts.filter((account) => account.account_type === 'credit_card');
  const ccAccountIds = new Set(creditCardAccounts.map((account) => account.id));

  const spending = buildSpendingBreakdown(allTransactions, ccAccountIds, monthStart, monthEnd);
  const trends = buildTrendReport(allTransactions, ccAccountIds, today);
  const transactionSummaries = buildTransactionSummaries(allTransactions);
  const debtItems = buildDebtItems(debts);

  // -------------------------------------------------------------------------
  // Call backend endpoints in parallel
  // -------------------------------------------------------------------------

  let monthlyPlanResult: PromiseSettledResult<MonthlyPlanResponse> | null = null;
  let forecastResult: PromiseSettledResult<CashFlowForecastResponse> | null = null;
  let savingsResult: PromiseSettledResult<SavingsReportResponse> | null = null;

  if (accessToken) {
    const calls: [
      Promise<MonthlyPlanResponse>,
      Promise<CashFlowForecastResponse>,
      Promise<SavingsReportResponse>,
    ] = [
      getMonthlyPlan(accessToken, {
        spending,
        trends,
        target_month: today.getMonth() + 1,
        target_year: today.getFullYear(),
      }),
      getCashFlowForecast(accessToken, { trends }),
      // `/savings` requires at least one transaction (min_length=1) — if every
      // fetched transaction was filtered out (zero amount or empty
      // description), reject locally instead of sending a guaranteed 422.
      transactionSummaries.length > 0
        ? getSavingsReport(accessToken, { transactions: transactionSummaries })
        : Promise.reject(new Error('No valid transactions for savings analysis')),
    ];

    [monthlyPlanResult, forecastResult, savingsResult] = await Promise.allSettled(calls);
  }

  const monthlyPlan: MonthlyPlan | null =
    monthlyPlanResult?.status === 'fulfilled' ? mapMonthlyPlan(monthlyPlanResult.value) : null;
  const savingsOpportunities: SavingsOpportunity[] | null =
    savingsResult?.status === 'fulfilled' ? mapSavingsOpportunities(savingsResult.value) : null;
  const forecastPoints: ForecastPoint[] | null =
    forecastResult?.status === 'fulfilled' ? mapForecastPoints(forecastResult.value) : null;

  // -------------------------------------------------------------------------
  // Debt payoff plan — only if there are borrowed debts and a positive
  // projected surplus to model a budget from.
  // -------------------------------------------------------------------------

  const projectedSavings = monthlyPlan?.projected_savings ?? 0;
  const monthlyBudget = Math.floor(projectedSavings);

  let debtReport: DebtOptimizationReportResponse | null = null;
  let debtSectionError = false;

  if (accessToken && debtItems.length > 0 && monthlyBudget > 0) {
    const debtResult = await Promise.allSettled([
      getDebtPayoffPlan(accessToken, {
        debts: debtItems,
        monthly_budget: monthlyBudget,
      }),
    ]);

    if (debtResult[0].status === 'fulfilled') {
      debtReport = debtResult[0].value;
    } else {
      debtSectionError = true;
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      {header}

      {/* Financial Health hero */}
      {monthlyPlan ? (
        <MonthlyPlanCard plan={monthlyPlan} />
      ) : (
        <SectionError title="Financial Health" />
      )}

      {/* Prioritised Action Feed — merges action items + savings opportunities */}
      {monthlyPlan || savingsOpportunities ? (
        <ActionFeed
          actionItems={monthlyPlan?.action_items ?? []}
          opportunities={savingsOpportunities ?? []}
        />
      ) : (
        <SectionError title="Prioritised Action Feed" />
      )}

      {/* Debt Payoff Plan */}
      {debtItems.length > 0 && (
        <>
          {debtReport ? (
            <DebtPayoffPlan report={debtReport} />
          ) : debtSectionError ? (
            <SectionError title="Debt Payoff Plan" />
          ) : monthlyBudget <= 0 ? (
            <Card>
              <CardHeader>
                <h2 className="text-base font-semibold text-ink">
                  Debt Payoff Plan
                </h2>
              </CardHeader>
              <CardBody>
                <p className="py-4 text-center text-sm text-ink-muted">
                  No surplus available to model a payoff plan
                  {projectedSavings > 0 && (
                    <>
                      {' '}
                      (projected savings of EGP {formatEGP(projectedSavings)} is too small to
                      model).
                    </>
                  )}
                </p>
              </CardBody>
            </Card>
          ) : null}
        </>
      )}

      {/* 3-Month Forecast */}
      {forecastPoints ? (
        <ForecastChart forecasts={forecastPoints} />
      ) : (
        <SectionError title="3-Month Forecast" />
      )}
    </div>
  );
}
