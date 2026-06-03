import Link from 'next/link';
import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { SpendingChart } from '@/components/dashboard/spending-chart';
import { RecentTransactions } from '@/components/dashboard/recent-transactions';
import { HealthScore } from '@/components/dashboard/health-score';
import type { Transaction } from '@/lib/types';
import type { Database } from '@finpilot/shared';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];
type DebtRow = Database['public']['Tables']['debts']['Row'];
type InstallmentRow = Database['public']['Tables']['installments']['Row'];
type AssetRow = Database['public']['Tables']['assets']['Row'];
type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';
type Tone = 'brand' | 'green' | 'blue' | 'amber' | 'red' | 'slate';

interface SpendingCategory {
  name: string;
  amount: number;
  color: string;
}

interface MonthlyTrend {
  label: string;
  income: number;
  cashExpenses: number;
  cardSpend: number;
  net: number;
  txCount: number;
}

interface MatrixRow {
  section: string;
  href: string;
  count: string;
  primaryLabel: string;
  primaryValue: string;
  secondaryLabel: string;
  secondaryValue: string;
  netEffect: number | null;
  status: string;
  statusVariant: BadgeVariant;
  note: string;
}

interface InsightItem {
  title: string;
  detail: string;
  variant: BadgeVariant;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CASH_ACCOUNT_TYPES = new Set(['savings', 'current', 'payroll']);
const FIXED_INCOME_ACCOUNT_TYPES = new Set(['certificate', 'deposit', 'term_deposit']);

const CATEGORY_COLORS: Record<string, string> = {
  'Food & Dining': '#f59e0b',
  Cash: '#8b5cf6',
  Shopping: '#3b82f6',
  Utilities: '#06b6d4',
  Entertainment: '#ec4899',
  Transport: '#22c55e',
  Income: '#10b981',
  Uncategorized: '#64748b',
  Other: '#6b7280',
};

const TONE_CLASSES: Record<Tone, { icon: string; accent: string; text: string }> = {
  brand: {
    icon: 'bg-brand-500/10 text-brand-500',
    accent: 'bg-brand-500',
    text: 'text-brand-500',
  },
  green: {
    icon: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
    accent: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
  },
  blue: {
    icon: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    accent: 'bg-blue-500',
    text: 'text-blue-600 dark:text-blue-400',
  },
  amber: {
    icon: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    accent: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
  },
  red: {
    icon: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
    accent: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
  },
  slate: {
    icon: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    accent: 'bg-slate-500',
    text: 'text-slate-600 dark:text-slate-400',
  },
};

// ---------------------------------------------------------------------------
// Formatting helpers
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

function formatAmount(amount: number, digits = 0): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount);
}

function formatCurrency(amount: number, digits = 0): string {
  return `EGP ${formatAmount(amount, digits)}`;
}

function formatSignedCurrency(amount: number): string {
  const sign = amount > 0 ? '+' : amount < 0 ? '-' : '';
  return `${sign}EGP ${formatAmount(Math.abs(amount))}`;
}

function formatPercent(value: number | null, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return 'No data';
  return `${value.toFixed(digits)}%`;
}

function currentMonthLabel(): string {
  return new Intl.DateTimeFormat('en-EG', { month: 'long', year: 'numeric' }).format(new Date());
}

function shortMonthLabel(date: Date): string {
  return new Intl.DateTimeFormat('en-EG', { month: 'short' }).format(date);
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function pctChange(previous: number, current: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function trendText(previous: number, current: number, goodWhenHigher: boolean): string {
  const change = pctChange(previous, current);
  if (change == null) return 'No prior month';
  if (change === 0) return 'Flat vs last month';
  const direction = change > 0 ? 'up' : 'down';
  const good = goodWhenHigher ? change > 0 : change < 0;
  const tone = good ? 'better' : 'higher';
  return `${Math.abs(change).toFixed(1)}% ${direction}, ${tone} vs last month`;
}

// ---------------------------------------------------------------------------
// Calculation helpers
// ---------------------------------------------------------------------------

function categoryColor(name: string): string {
  return CATEGORY_COLORS[name] ?? '#6b7280';
}

function isInRange(date: string, start: string, end: string): boolean {
  return date >= start && date <= end;
}

function buildSpendingCategories(
  transactions: TransactionRow[],
  monthStart: string,
  monthEnd: string,
): SpendingCategory[] {
  const totals: Record<string, number> = {};

  for (const tx of transactions) {
    if (tx.transaction_type !== 'debit') continue;
    if (!isInRange(tx.transaction_date, monthStart, monthEnd)) continue;

    const cat = tx.category ?? 'Uncategorized';
    totals[cat] = (totals[cat] ?? 0) + parseAmount(tx.amount);
  }

  return Object.entries(totals)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 7)
    .map(([name, amount]) => ({ name, amount, color: categoryColor(name) }));
}

function toTransaction(row: TransactionRow): Transaction {
  return {
    id: row.id,
    description: row.description,
    amount: parseAmount(row.amount),
    transaction_type: row.transaction_type as 'debit' | 'credit',
    transaction_date: row.transaction_date,
    category: row.category,
    currency: row.currency,
    account_id: row.account_id,
  };
}

function computeMonthsElapsed(startDate: string, billingDay: number | null, today: Date): number {
  const start = new Date(startDate);
  if (Number.isNaN(start.getTime())) return 0;

  const day = billingDay ?? start.getDate();
  const elapsed =
    (today.getFullYear() - start.getFullYear()) * 12 +
    (today.getMonth() - start.getMonth()) -
    (today.getDate() < day ? 1 : 0);

  return Math.max(0, elapsed);
}

function installmentRemainingMonths(item: InstallmentRow, today: Date): number {
  const elapsed = computeMonthsElapsed(item.start_date, item.billing_day, today);
  return Math.max(0, item.total_months - elapsed);
}

function daysUntil(dateStr: string, today: Date): number {
  const target = new Date(dateStr);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  target.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
}

function buildMonthlyTrends(
  transactions: TransactionRow[],
  ccAccountIds: Set<string>,
  today: Date,
): MonthlyTrend[] {
  const trends: MonthlyTrend[] = [];

  for (let offset = 5; offset >= 0; offset -= 1) {
    const monthDate = new Date(today.getFullYear(), today.getMonth() - offset, 1);
    const start = dateKey(monthDate);
    const end = dateKey(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0));

    let income = 0;
    let cashExpenses = 0;
    let cardSpend = 0;
    let txCount = 0;

    for (const tx of transactions) {
      if (!isInRange(tx.transaction_date, start, end)) continue;
      txCount += 1;

      const amount = parseAmount(tx.amount);
      const isCard = ccAccountIds.has(tx.account_id);

      if (tx.transaction_type === 'credit' && !isCard) {
        income += amount;
      } else if (tx.transaction_type === 'debit' && !isCard) {
        cashExpenses += amount;
      } else if (tx.transaction_type === 'debit' && isCard) {
        cardSpend += amount;
      }
    }

    trends.push({
      label: shortMonthLabel(monthDate),
      income,
      cashExpenses,
      cardSpend,
      net: income - cashExpenses,
      txCount,
    });
  }

  return trends;
}

function weightedAverageRate(accounts: BankAccountRow[]): number | null {
  let weighted = 0;
  let denominator = 0;

  for (const account of accounts) {
    const balance = parseAmount(account.balance);
    const rate = account.interest_rate == null ? null : parseAmount(account.interest_rate);
    if (rate == null || balance <= 0) continue;
    weighted += balance * rate;
    denominator += balance;
  }

  return denominator > 0 ? (weighted / denominator) * 100 : null;
}

function computeHealthScore(input: {
  monthlyIncome: number;
  monthlyExpenses: number;
  monthlyObligations: number;
  liquidBalance: number;
  grossAssets: number;
  totalLiabilities: number;
  creditUtilization: number | null;
  txCount: number;
}): number {
  const {
    monthlyIncome,
    monthlyExpenses,
    monthlyObligations,
    liquidBalance,
    grossAssets,
    totalLiabilities,
    creditUtilization,
    txCount,
  } = input;

  let score = 52;

  if (monthlyIncome > 0) {
    const savingsRate = (monthlyIncome - monthlyExpenses) / monthlyIncome;
    score += Math.max(-20, Math.min(25, savingsRate * 80));

    const obligationPressure = monthlyObligations / monthlyIncome;
    score -= Math.max(0, Math.min(15, obligationPressure * 35));
  }

  const monthlyOutflow = monthlyExpenses + monthlyObligations;
  if (monthlyOutflow > 0) {
    const coverageMonths = liquidBalance / monthlyOutflow;
    score += Math.max(0, Math.min(12, coverageMonths * 3));
  }

  if (grossAssets > 0) {
    const liabilityRatio = totalLiabilities / grossAssets;
    score -= Math.max(0, Math.min(18, liabilityRatio * 28));
  }

  if (creditUtilization != null && creditUtilization > 30) {
    score -= Math.min(12, ((creditUtilization - 30) / 70) * 12);
  }

  score += Math.min(9, txCount / 10);

  return Math.round(Math.max(0, Math.min(100, score)));
}

function scoreStatus(score: number): { label: string; variant: BadgeVariant } {
  if (score >= 80) return { label: 'Excellent', variant: 'success' };
  if (score >= 60) return { label: 'Healthy', variant: 'info' };
  if (score >= 40) return { label: 'Watch', variant: 'warning' };
  return { label: 'Needs focus', variant: 'danger' };
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function WalletIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12V8a3 3 0 00-3-3H5a3 3 0 00-3 3v8a3 3 0 003 3h13a3 3 0 003-3v-4zm0 0h-5a2 2 0 100 4h5" />
    </svg>
  );
}

function NetWorthIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3M5 11h14M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  );
}

function PulseIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 12h4l2-6 4 12 2-6h6" />
    </svg>
  );
}

function LiabilityIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.7 0-3 .9-3 2s1.3 2 3 2 3 .9 3 2-1.3 2-3 2m0-8V6m0 10v2m9-6a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Local UI components
// ---------------------------------------------------------------------------

function MetricTile({
  label,
  value,
  helper,
  icon,
  tone,
}: {
  label: string;
  value: string;
  helper: string;
  icon: React.ReactNode;
  tone: Tone;
}) {
  return (
    <Card>
      <CardBody className="p-4 sm:p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className={`rounded-lg p-2 ${TONE_CLASSES[tone].icon}`}>{icon}</div>
          <span className={`mt-1 h-2 w-2 rounded-full ${TONE_CLASSES[tone].accent}`} aria-hidden="true" />
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        <p className="mt-1 break-words text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
          {value}
        </p>
        <p className="mt-2 min-h-8 text-xs leading-4 text-gray-500 dark:text-gray-400">
          {helper}
        </p>
      </CardBody>
    </Card>
  );
}

function CompositionBar({
  items,
}: {
  items: Array<{ label: string; value: number; tone: Tone }>;
}) {
  const total = items.reduce((sum, item) => sum + Math.max(0, item.value), 0);

  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
        {items.map((item) => {
          const pct = total > 0 ? (Math.max(0, item.value) / total) * 100 : 0;
          return (
            <span
              key={item.label}
              className={TONE_CLASSES[item.tone].accent}
              style={{ width: `${clampPercent(pct)}%` }}
              title={`${item.label}: ${formatCurrency(item.value)}`}
            />
          );
        })}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {items.map((item) => {
          const pct = total > 0 ? (Math.max(0, item.value) / total) * 100 : 0;
          return (
            <div key={item.label} className="flex items-center justify-between gap-3 text-sm">
              <span className="flex min-w-0 items-center gap-2 text-gray-600 dark:text-gray-300">
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${TONE_CLASSES[item.tone].accent}`} />
                <span className="truncate">{item.label}</span>
              </span>
              <span className="shrink-0 text-right text-xs font-medium tabular-nums text-gray-500 dark:text-gray-400">
                {formatPercent(pct)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PortfolioComposition({
  assetItems,
  liabilityItems,
  grossAssets,
  totalLiabilities,
  netWorth,
}: {
  assetItems: Array<{ label: string; value: number; tone: Tone }>;
  liabilityItems: Array<{ label: string; value: number; tone: Tone }>;
  grossAssets: number;
  totalLiabilities: number;
  netWorth: number;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">Portfolio Equation</h2>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              Gross assets minus liabilities equals your tracked net worth
            </p>
          </div>
          <Badge variant={netWorth >= 0 ? 'success' : 'danger'}>
            {netWorth >= 0 ? 'Positive net worth' : 'Negative net worth'}
          </Badge>
        </div>
      </CardHeader>
      <CardBody>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_auto_1fr] lg:items-start">
          <div>
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase text-gray-400 dark:text-gray-500">Assets</p>
                <p className="mt-1 text-xl font-bold tabular-nums text-gray-900 dark:text-white">
                  {formatCurrency(grossAssets)}
                </p>
              </div>
            </div>
            <CompositionBar items={assetItems} />
          </div>

          <div className="hidden h-full w-px bg-gray-200 dark:bg-gray-800 lg:block" />

          <div>
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase text-gray-400 dark:text-gray-500">Liabilities</p>
                <p className="mt-1 text-xl font-bold tabular-nums text-gray-900 dark:text-white">
                  {formatCurrency(totalLiabilities)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-500 dark:text-gray-400">Net worth</p>
                <p className={`text-lg font-bold tabular-nums ${netWorth >= 0 ? TONE_CLASSES.green.text : TONE_CLASSES.red.text}`}>
                  {formatSignedCurrency(netWorth)}
                </p>
              </div>
            </div>
            <CompositionBar items={liabilityItems} />
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function AnalyticsMatrix({ rows }: { rows: MatrixRow[] }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">Cross-Tab Matrix</h2>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              Every dashboard tab rolled into one comparable set of numbers
            </p>
          </div>
          <Badge variant="info">{rows.length} live sections</Badge>
        </div>
      </CardHeader>
      <CardBody className="p-0">
        <div className="divide-y divide-gray-100 dark:divide-gray-800 lg:hidden">
          {rows.map((row) => (
            <div key={row.section} className="px-4 py-4">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <Link href={row.href} className="text-sm font-semibold text-gray-900 hover:text-brand-500 dark:text-white">
                    {row.section}
                  </Link>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{row.count}</p>
                </div>
                <Badge variant={row.statusVariant}>{row.status}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <MatrixMobileMetric label={row.primaryLabel} value={row.primaryValue} />
                <MatrixMobileMetric label={row.secondaryLabel} value={row.secondaryValue} />
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                <span className="text-gray-500 dark:text-gray-400">Net worth effect</span>
                <span className={`font-semibold tabular-nums ${row.netEffect != null && row.netEffect < 0 ? TONE_CLASSES.red.text : TONE_CLASSES.green.text}`}>
                  {row.netEffect == null ? 'Signal only' : formatSignedCurrency(row.netEffect)}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-gray-500 dark:text-gray-400">{row.note}</p>
            </div>
          ))}
        </div>

        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <th className="px-6 py-3 text-left text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                  Tab
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                  Primary
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                  Secondary
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                  Net Effect
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {rows.map((row) => (
                <tr key={row.section} className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/50">
                  <td className="px-6 py-4 align-top">
                    <Link href={row.href} className="font-semibold text-gray-900 hover:text-brand-500 dark:text-white">
                      {row.section}
                    </Link>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{row.count}</p>
                    <p className="mt-2 max-w-xs text-xs leading-5 text-gray-500 dark:text-gray-400">{row.note}</p>
                  </td>
                  <td className="px-6 py-4 align-top">
                    <p className="text-xs text-gray-500 dark:text-gray-400">{row.primaryLabel}</p>
                    <p className="mt-1 font-semibold tabular-nums text-gray-900 dark:text-white">{row.primaryValue}</p>
                  </td>
                  <td className="px-6 py-4 align-top">
                    <p className="text-xs text-gray-500 dark:text-gray-400">{row.secondaryLabel}</p>
                    <p className="mt-1 font-semibold tabular-nums text-gray-900 dark:text-white">{row.secondaryValue}</p>
                  </td>
                  <td className="px-6 py-4 text-right align-top">
                    <span className={`font-semibold tabular-nums ${row.netEffect != null && row.netEffect < 0 ? TONE_CLASSES.red.text : TONE_CLASSES.green.text}`}>
                      {row.netEffect == null ? 'Signal only' : formatSignedCurrency(row.netEffect)}
                    </span>
                  </td>
                  <td className="px-6 py-4 align-top">
                    <Badge variant={row.statusVariant}>{row.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}

function MatrixMobileMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800/50">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className="mt-1 break-words text-sm font-semibold tabular-nums text-gray-900 dark:text-white">
        {value}
      </p>
    </div>
  );
}

function CashFlowTrend({ trends }: { trends: MonthlyTrend[] }) {
  const maxValue = Math.max(
    1,
    ...trends.flatMap((month) => [month.income, month.cashExpenses, month.cardSpend]),
  );

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">Six-Month Activity</h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          Income, cash expenses, and credit-card spend shown side by side
        </p>
      </CardHeader>
      <CardBody>
        <div className="space-y-4">
          {trends.map((month) => (
            <div key={month.label} className="grid grid-cols-[2.75rem_1fr] items-center gap-3">
              <span className="text-xs font-medium text-gray-500 dark:text-gray-400">{month.label}</span>
              <div>
                <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                  <span className="text-gray-500 dark:text-gray-400">
                    Net {formatSignedCurrency(month.net)}
                  </span>
                  <span className="tabular-nums text-gray-400 dark:text-gray-500">
                    {month.txCount} tx
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-1">
                  <TrendBar label="Income" value={month.income} maxValue={maxValue} tone="green" />
                  <TrendBar label="Cash" value={month.cashExpenses} maxValue={maxValue} tone="amber" />
                  <TrendBar label="Card" value={month.cardSpend} maxValue={maxValue} tone="blue" />
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function TrendBar({
  label,
  value,
  maxValue,
  tone,
}: {
  label: string;
  value: number;
  maxValue: number;
  tone: Tone;
}) {
  const height = clampPercent((value / maxValue) * 100);

  return (
    <div className="flex h-16 flex-col justify-end rounded-md bg-gray-50 px-1.5 pb-1.5 dark:bg-gray-800/50" title={`${label}: ${formatCurrency(value)}`}>
      <div className={`min-h-1 rounded-sm ${TONE_CLASSES[tone].accent}`} style={{ height: `${height}%` }} />
      <span className="mt-1 truncate text-center text-[10px] leading-none text-gray-400 dark:text-gray-500">
        {label}
      </span>
    </div>
  );
}

function InsightsPanel({ insights }: { insights: InsightItem[] }) {
  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">Live Signals</h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          Recommendation inputs generated from current dashboard numbers
        </p>
      </CardHeader>
      <CardBody>
        <div className="space-y-3">
          {insights.map((item) => (
            <div key={item.title} className="flex items-start justify-between gap-4 rounded-lg border border-gray-100 px-3 py-3 dark:border-gray-800">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark:text-white">{item.title}</p>
                <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">{item.detail}</p>
              </div>
              <Badge variant={item.variant}>Signal</Badge>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page (Server Component - data fetched at request time with RLS)
// ---------------------------------------------------------------------------

export default async function DashboardPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [accountsResult, transactionsResult, debtsResult, installmentsResult, assetsResult] = await Promise.all([
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
      .limit(1500),
    supabase
      .from('debts')
      .select('*')
      .eq('user_id', userId)
      .neq('status', 'settled'),
    supabase
      .from('installments')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true),
    supabase
      .from('assets')
      .select('*')
      .eq('user_id', userId),
  ]);

  const accounts: BankAccountRow[] = accountsResult.data ?? [];
  const allTransactions: TransactionRow[] = transactionsResult.data ?? [];
  const debts: DebtRow[] = debtsResult.data ?? [];
  const installments: InstallmentRow[] = installmentsResult.data ?? [];
  const assets: AssetRow[] = assetsResult.data ?? [];

  const today = new Date();
  const todayStr = dateKey(today);
  const monthStart = dateKey(new Date(today.getFullYear(), today.getMonth(), 1));
  const monthEnd = dateKey(new Date(today.getFullYear(), today.getMonth() + 1, 0));
  const previousMonthStart = dateKey(new Date(today.getFullYear(), today.getMonth() - 1, 1));
  const previousMonthEnd = dateKey(new Date(today.getFullYear(), today.getMonth(), 0));

  // Account buckets
  const liquidAccounts = accounts.filter((account) => CASH_ACCOUNT_TYPES.has(account.account_type));
  const fixedIncomeAccounts = accounts.filter((account) => FIXED_INCOME_ACCOUNT_TYPES.has(account.account_type));
  const creditCardAccounts = accounts.filter((account) => account.account_type === 'credit_card');
  const otherBankAssetAccounts = accounts.filter(
    (account) =>
      account.account_type !== 'credit_card' &&
      !CASH_ACCOUNT_TYPES.has(account.account_type) &&
      !FIXED_INCOME_ACCOUNT_TYPES.has(account.account_type),
  );

  const liquidBalance = liquidAccounts.reduce((sum, account) => sum + parseAmount(account.balance), 0);
  const fixedIncomeValue = fixedIncomeAccounts.reduce((sum, account) => sum + parseAmount(account.balance), 0);
  const otherBankAssetValue = otherBankAssetAccounts.reduce((sum, account) => sum + parseAmount(account.balance), 0);
  const bankAssetValue = liquidBalance + fixedIncomeValue + otherBankAssetValue;

  const creditOutstanding = creditCardAccounts.reduce((sum, account) => sum + parseAmount(account.balance), 0);
  const creditLimit = creditCardAccounts.reduce((sum, account) => sum + parseAmount(account.credit_limit), 0);
  const availableCredit = Math.max(0, creditLimit - creditOutstanding);
  const creditUtilization = creditLimit > 0 ? (creditOutstanding / creditLimit) * 100 : null;
  const minimumCardPayments = creditCardAccounts.reduce((sum, account) => sum + parseAmount(account.minimum_payment), 0);
  const billedAmount = creditCardAccounts.reduce((sum, account) => sum + parseAmount(account.billed_amount), 0);
  const unbilledAmount = creditCardAccounts.reduce((sum, account) => sum + parseAmount(account.unbilled_amount), 0);

  // Manual assets are valued with stored current value, falling back to cost.
  const assetCurrentValue = assets.reduce(
    (sum, asset) => sum + parseAmount(asset.current_value_egp ?? asset.purchase_price_egp),
    0,
  );
  const assetCost = assets.reduce((sum, asset) => sum + parseAmount(asset.purchase_price_egp), 0);
  const assetGainLoss = assetCurrentValue - assetCost;
  const assetReturnPct = assetCost > 0 ? (assetGainLoss / assetCost) * 100 : null;

  // Debts
  const lentDebts = debts.filter((debt) => debt.debt_type === 'lent');
  const borrowedDebts = debts.filter((debt) => debt.debt_type === 'borrowed');
  const totalLent = lentDebts.reduce((sum, debt) => sum + parseAmount(debt.outstanding_balance), 0);
  const totalBorrowed = borrowedDebts.reduce((sum, debt) => sum + parseAmount(debt.outstanding_balance), 0);
  const overdueBorrowedCount = borrowedDebts.filter((debt) => debt.due_date != null && debt.due_date < todayStr).length;
  const collectDueSoonCount = lentDebts.filter((debt) => {
    if (debt.due_date == null) return false;
    const days = daysUntil(debt.due_date, today);
    return days >= 0 && days <= 30;
  }).length;

  // Installments
  const activeInstallments = installments.filter((item) => installmentRemainingMonths(item, today) > 0);
  const installmentMonthly = activeInstallments.reduce((sum, item) => sum + parseAmount(item.monthly_amount), 0);
  const installmentLiability = activeInstallments.reduce(
    (sum, item) => sum + installmentRemainingMonths(item, today) * parseAmount(item.monthly_amount),
    0,
  );
  const installmentDueSoonCount = activeInstallments.filter((item) => {
    const billingDay = item.billing_day ?? new Date(item.start_date).getDate();
    const dueDate = new Date(today.getFullYear(), today.getMonth(), billingDay);
    if (dueDate < today) dueDate.setMonth(dueDate.getMonth() + 1);
    const days = daysUntil(dateKey(dueDate), today);
    return days >= 0 && days <= 10;
  }).length;

  // Transactions and cash flow
  const ccAccountIds = new Set(creditCardAccounts.map((account) => account.id));
  let monthlyIncome = 0;
  let monthlyCashExpenses = 0;
  let monthlyCardSpend = 0;
  let previousIncome = 0;
  let previousCashExpenses = 0;
  let previousCardSpend = 0;
  let currentMonthTxCount = 0;

  for (const tx of allTransactions) {
    const amount = parseAmount(tx.amount);
    const isCard = ccAccountIds.has(tx.account_id);

    if (isInRange(tx.transaction_date, monthStart, monthEnd)) {
      currentMonthTxCount += 1;
      if (tx.transaction_type === 'credit' && !isCard) monthlyIncome += amount;
      if (tx.transaction_type === 'debit' && !isCard) monthlyCashExpenses += amount;
      if (tx.transaction_type === 'debit' && isCard) monthlyCardSpend += amount;
    }

    if (isInRange(tx.transaction_date, previousMonthStart, previousMonthEnd)) {
      if (tx.transaction_type === 'credit' && !isCard) previousIncome += amount;
      if (tx.transaction_type === 'debit' && !isCard) previousCashExpenses += amount;
      if (tx.transaction_type === 'debit' && isCard) previousCardSpend += amount;
    }
  }

  const monthlyCashFlow = monthlyIncome - monthlyCashExpenses;
  const trackedMonthlySpend = monthlyCashExpenses + monthlyCardSpend;
  const savingsRate = monthlyIncome > 0 ? (monthlyCashFlow / monthlyIncome) * 100 : null;
  const monthlyObligations = installmentMonthly + minimumCardPayments;
  const obligationPressure = monthlyIncome > 0 ? (monthlyObligations / monthlyIncome) * 100 : null;
  const coverageMonths = monthlyCashExpenses + monthlyObligations > 0
    ? liquidBalance / (monthlyCashExpenses + monthlyObligations)
    : null;

  const grossAssets = bankAssetValue + assetCurrentValue + totalLent;
  const totalLiabilities = creditOutstanding + totalBorrowed + installmentLiability;
  const netWorth = grossAssets - totalLiabilities;

  const healthScore = computeHealthScore({
    monthlyIncome,
    monthlyExpenses: monthlyCashExpenses,
    monthlyObligations,
    liquidBalance,
    grossAssets,
    totalLiabilities,
    creditUtilization,
    txCount: allTransactions.length,
  });
  const health = scoreStatus(healthScore);

  const weightedCertificateRate = weightedAverageRate(fixedIncomeAccounts);
  const certificatesMaturingSoon = fixedIncomeAccounts.filter((account) => {
    if (account.maturity_date == null) return false;
    const days = daysUntil(account.maturity_date, today);
    return days >= 0 && days <= 60;
  }).length;

  const spendingCategories = buildSpendingCategories(allTransactions, monthStart, monthEnd);
  const recentTransactions: Transaction[] = allTransactions.slice(0, 10).map(toTransaction);
  const monthlyTrends = buildMonthlyTrends(allTransactions, ccAccountIds, today);

  const insights: InsightItem[] = [];

  if (monthlyCashFlow < 0) {
    insights.push({
      title: 'Cash flow is negative this month',
      detail: `${formatCurrency(monthlyCashExpenses)} in cash expenses is above ${formatCurrency(monthlyIncome)} income.`,
      variant: 'danger',
    });
  } else if (savingsRate != null && savingsRate >= 20) {
    insights.push({
      title: 'Savings rate is healthy',
      detail: `${formatPercent(savingsRate)} of income stayed after cash expenses this month.`,
      variant: 'success',
    });
  }

  if (creditUtilization != null && creditUtilization >= 70) {
    insights.push({
      title: 'Credit utilization is high',
      detail: `${formatPercent(creditUtilization)} of card limits are currently used across ${creditCardAccounts.length} card account(s).`,
      variant: 'danger',
    });
  } else if (creditCardAccounts.length > 0) {
    insights.push({
      title: 'Credit capacity is visible',
      detail: `${formatCurrency(availableCredit)} is still available against ${formatCurrency(creditLimit)} total credit limits.`,
      variant: creditUtilization != null && creditUtilization >= 40 ? 'warning' : 'info',
    });
  }

  if (obligationPressure != null && obligationPressure >= 35) {
    insights.push({
      title: 'Monthly obligations need attention',
      detail: `${formatCurrency(monthlyObligations)} due monthly equals ${formatPercent(obligationPressure)} of current income.`,
      variant: 'warning',
    });
  }

  if (coverageMonths != null && coverageMonths < 3) {
    insights.push({
      title: 'Liquid runway is below three months',
      detail: `Liquid balance covers about ${coverageMonths.toFixed(1)} month(s) of cash expenses plus fixed obligations.`,
      variant: 'warning',
    });
  }

  if (certificatesMaturingSoon > 0) {
    insights.push({
      title: 'Certificate maturity coming up',
      detail: `${certificatesMaturingSoon} certificate or deposit instrument(s) mature within 60 days.`,
      variant: 'info',
    });
  }

  if (insights.length === 0) {
    insights.push({
      title: 'Connect more data for deeper analysis',
      detail: 'No urgent signals were detected from the currently synced accounts, assets, debts, and installments.',
      variant: 'default',
    });
  }

  const matrixRows: MatrixRow[] = [
    {
      section: 'Accounts',
      href: '/dashboard/accounts',
      count: `${liquidAccounts.length} liquid account${liquidAccounts.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Liquid balance',
      primaryValue: formatCurrency(liquidBalance),
      secondaryLabel: 'Cash flow',
      secondaryValue: formatSignedCurrency(monthlyCashFlow),
      netEffect: liquidBalance,
      status: monthlyCashFlow >= 0 ? 'Cash positive' : 'Cash deficit',
      statusVariant: monthlyCashFlow >= 0 ? 'success' : 'danger',
      note: trendText(previousIncome - previousCashExpenses, monthlyCashFlow, true),
    },
    {
      section: 'Transactions',
      href: '/dashboard/transactions',
      count: `${currentMonthTxCount} transaction${currentMonthTxCount !== 1 ? 's' : ''} this month`,
      primaryLabel: 'Income',
      primaryValue: formatCurrency(monthlyIncome),
      secondaryLabel: 'Cash expenses',
      secondaryValue: formatCurrency(monthlyCashExpenses),
      netEffect: monthlyCashFlow,
      status: savingsRate != null && savingsRate >= 20 ? 'Saving well' : monthlyCashFlow >= 0 ? 'Balanced' : 'Overspending',
      statusVariant: savingsRate != null && savingsRate >= 20 ? 'success' : monthlyCashFlow >= 0 ? 'info' : 'danger',
      note: `Savings rate: ${formatPercent(savingsRate)}. Tracked spend including cards: ${formatCurrency(trackedMonthlySpend)}.`,
    },
    {
      section: 'Credit Cards',
      href: '/dashboard/credit-cards',
      count: `${creditCardAccounts.length} card account${creditCardAccounts.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Outstanding',
      primaryValue: formatCurrency(creditOutstanding),
      secondaryLabel: 'Utilization',
      secondaryValue: formatPercent(creditUtilization),
      netEffect: -creditOutstanding,
      status: creditUtilization == null ? 'No limit data' : creditUtilization < 30 ? 'Low use' : creditUtilization < 70 ? 'Moderate use' : 'High use',
      statusVariant: creditUtilization == null ? 'default' : creditUtilization < 30 ? 'success' : creditUtilization < 70 ? 'warning' : 'danger',
      note: `${formatCurrency(billedAmount)} billed, ${formatCurrency(unbilledAmount)} unbilled. Card spend is ${trendText(previousCardSpend, monthlyCardSpend, false)}.`,
    },
    {
      section: 'Certificates',
      href: '/dashboard/certificates',
      count: `${fixedIncomeAccounts.length} instrument${fixedIncomeAccounts.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Principal',
      primaryValue: formatCurrency(fixedIncomeValue),
      secondaryLabel: 'Avg rate',
      secondaryValue: formatPercent(weightedCertificateRate),
      netEffect: fixedIncomeValue,
      status: certificatesMaturingSoon > 0 ? 'Maturing soon' : 'Locked savings',
      statusVariant: certificatesMaturingSoon > 0 ? 'warning' : 'success',
      note: certificatesMaturingSoon > 0
        ? `${certificatesMaturingSoon} mature within 60 days.`
        : 'No maturities detected in the next 60 days.',
    },
    {
      section: 'Assets',
      href: '/dashboard/assets',
      count: `${assets.length} tracked asset${assets.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Current value',
      primaryValue: formatCurrency(assetCurrentValue),
      secondaryLabel: 'Gain / loss',
      secondaryValue: formatSignedCurrency(assetGainLoss),
      netEffect: assetCurrentValue,
      status: assetGainLoss >= 0 ? 'Gain' : 'Loss',
      statusVariant: assetGainLoss >= 0 ? 'success' : 'warning',
      note: `Return on stored values: ${formatPercent(assetReturnPct)}.`,
    },
    {
      section: 'Debts',
      href: '/dashboard/debts',
      count: `${debts.length} active debt${debts.length !== 1 ? 's' : ''}`,
      primaryLabel: 'To collect',
      primaryValue: formatCurrency(totalLent),
      secondaryLabel: 'You owe',
      secondaryValue: formatCurrency(totalBorrowed),
      netEffect: totalLent - totalBorrowed,
      status: overdueBorrowedCount > 0 ? 'Overdue owed' : totalLent >= totalBorrowed ? 'Net collect' : 'Net owe',
      statusVariant: overdueBorrowedCount > 0 ? 'danger' : totalLent >= totalBorrowed ? 'success' : 'warning',
      note: collectDueSoonCount > 0
        ? `${collectDueSoonCount} receivable(s) due within 30 days.`
        : 'No receivables due within the next 30 days.',
    },
    {
      section: 'Installments',
      href: '/dashboard/installments',
      count: `${activeInstallments.length} active plan${activeInstallments.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Monthly due',
      primaryValue: formatCurrency(installmentMonthly),
      secondaryLabel: 'Remaining',
      secondaryValue: formatCurrency(installmentLiability),
      netEffect: -installmentLiability,
      status: installmentDueSoonCount > 0 ? 'Due soon' : 'Scheduled',
      statusVariant: installmentDueSoonCount > 0 ? 'warning' : 'info',
      note: `${formatCurrency(monthlyObligations)} total monthly obligations including card minimums.`,
    },
    {
      section: 'Recommendations',
      href: '/dashboard/recommendations',
      count: `${insights.length} live signal${insights.length !== 1 ? 's' : ''}`,
      primaryLabel: 'Health score',
      primaryValue: `${healthScore}/100`,
      secondaryLabel: 'Obligation load',
      secondaryValue: formatPercent(obligationPressure),
      netEffect: null,
      status: health.label,
      statusVariant: health.variant,
      note: 'Signals are derived from the same live totals used by this dashboard.',
    },
  ];

  const assetItems = [
    { label: 'Liquid accounts', value: liquidBalance, tone: 'green' as Tone },
    { label: 'Certificates', value: fixedIncomeValue, tone: 'amber' as Tone },
    { label: 'Other bank assets', value: otherBankAssetValue, tone: 'blue' as Tone },
    { label: 'Tracked assets', value: assetCurrentValue, tone: 'brand' as Tone },
    { label: 'Receivables', value: totalLent, tone: 'slate' as Tone },
  ].filter((item) => item.value > 0);

  const liabilityItems = [
    { label: 'Credit cards', value: creditOutstanding, tone: 'red' as Tone },
    { label: 'Borrowed debts', value: totalBorrowed, tone: 'amber' as Tone },
    { label: 'Installments', value: installmentLiability, tone: 'blue' as Tone },
  ].filter((item) => item.value > 0);

  const hasData = accounts.length > 0 || allTransactions.length > 0 || assets.length > 0 || debts.length > 0 || installments.length > 0;

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Analytics Overview</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {hasData
              ? `Your cross-tab financial matrix for ${currentMonthLabel()}`
              : 'Connect data in Settings to unlock the full analytics matrix'}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-left shadow-sm dark:border-gray-800 dark:bg-gray-900 sm:text-right">
          <p className="text-xs text-gray-500 dark:text-gray-400">Financial health</p>
          <p className="mt-1 text-xl font-bold tabular-nums text-gray-900 dark:text-white">{healthScore}/100</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <MetricTile
          label="Net Worth"
          value={formatSignedCurrency(netWorth)}
          helper={`${formatCurrency(grossAssets)} assets minus ${formatCurrency(totalLiabilities)} liabilities`}
          icon={<NetWorthIcon />}
          tone={netWorth >= 0 ? 'green' : 'red'}
        />
        <MetricTile
          label="Liquid Balance"
          value={formatCurrency(liquidBalance)}
          helper={coverageMonths == null ? 'Runway needs expense data' : `${coverageMonths.toFixed(1)} month runway at current burn`}
          icon={<WalletIcon />}
          tone="brand"
        />
        <MetricTile
          label="Monthly Cash Flow"
          value={formatSignedCurrency(monthlyCashFlow)}
          helper={trendText(previousIncome - previousCashExpenses, monthlyCashFlow, true)}
          icon={<PulseIcon />}
          tone={monthlyCashFlow >= 0 ? 'green' : 'red'}
        />
        <MetricTile
          label="Total Liabilities"
          value={formatCurrency(totalLiabilities)}
          helper={`${formatCurrency(creditOutstanding)} cards, ${formatCurrency(installmentLiability)} installments`}
          icon={<LiabilityIcon />}
          tone={totalLiabilities > grossAssets ? 'red' : 'amber'}
        />
        <MetricTile
          label="Monthly Obligations"
          value={formatCurrency(monthlyObligations)}
          helper={`${formatPercent(obligationPressure)} of income from installments and card minimums`}
          icon={<CalendarIcon />}
          tone={obligationPressure != null && obligationPressure >= 35 ? 'red' : 'blue'}
        />
      </div>

      <PortfolioComposition
        assetItems={assetItems.length > 0 ? assetItems : [{ label: 'No assets yet', value: 1, tone: 'slate' }]}
        liabilityItems={liabilityItems.length > 0 ? liabilityItems : [{ label: 'No liabilities yet', value: 1, tone: 'slate' }]}
        grossAssets={grossAssets}
        totalLiabilities={totalLiabilities}
        netWorth={netWorth}
      />

      <AnalyticsMatrix rows={matrixRows} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <CashFlowTrend trends={monthlyTrends} />
        <InsightsPanel insights={insights} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SpendingChart categories={spendingCategories} />
        <HealthScore score={healthScore} />
      </div>

      <RecentTransactions transactions={recentTransactions} />
    </div>
  );
}
