import { createClient } from '@/lib/supabase/server';
import { AccountCard } from '@/components/dashboard/account-card';
import { SpendingChart } from '@/components/dashboard/spending-chart';
import { RecentTransactions } from '@/components/dashboard/recent-transactions';
import { HealthScore } from '@/components/dashboard/health-score';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Transaction } from '@/lib/types';
import type { Database } from '@finpilot/shared';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];

interface SpendingCategory {
  name: string;
  amount: number;
  color: string;
}

interface AccountGroup {
  label: string;
  accounts: BankAccountRow[];
  totalBalance: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CATEGORY_COLORS: Record<string, string> = {
  'Food & Dining': '#f59e0b',
  'Cash': '#8b5cf6',
  'Shopping': '#3b82f6',
  'Utilities': '#06b6d4',
  'Entertainment': '#ec4899',
  'Transport': '#22c55e',
  'Income': '#10b981',
  'Other': '#6b7280',
};

function categoryColor(name: string): string {
  return CATEGORY_COLORS[name] ?? '#6b7280';
}

function currentMonthLabel(): string {
  return new Intl.DateTimeFormat('en-EG', { month: 'long', year: 'numeric' }).format(new Date());
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function buildSpendingCategories(transactions: TransactionRow[]): SpendingCategory[] {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);

  const totals: Record<string, number> = {};
  for (const tx of transactions) {
    if (tx.transaction_type !== 'debit') continue;
    if (tx.transaction_date < monthStart) continue;
    const cat = tx.category ?? 'Other';
    totals[cat] = (totals[cat] ?? 0) + tx.amount;
  }

  return Object.entries(totals)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)
    .map(([name, amount]) => ({ name, amount, color: categoryColor(name) }));
}

function toTransaction(row: TransactionRow): Transaction {
  return {
    id: row.id,
    description: row.description,
    amount: row.amount,
    transaction_type: row.transaction_type as 'debit' | 'credit',
    transaction_date: row.transaction_date,
    category: row.category,
    currency: row.currency,
  };
}

function computeHealthScore(totalIncome: number, totalExpenses: number, txCount: number): number {
  if (txCount === 0) return 50;
  const savingsRate = totalIncome > 0 ? (totalIncome - totalExpenses) / totalIncome : 0;
  const savingsPts = Math.round(Math.max(0, Math.min(1, savingsRate)) * 30);
  const volumePts = Math.min(20, Math.round((txCount / 20) * 20));
  return Math.min(100, 50 + savingsPts + volumePts);
}

function accountTypeBadgeVariant(
  type: string,
): 'default' | 'success' | 'info' | 'warning' | 'danger' {
  switch (type) {
    case 'savings': return 'success';
    case 'current': return 'default';
    case 'payroll': return 'info';
    case 'credit_card': return 'warning';
    case 'certificate':
    case 'deposit': return 'danger';
    default: return 'default';
  }
}

function accountTypeLabel(type: string): string {
  switch (type) {
    case 'savings': return 'Savings';
    case 'current': return 'Current';
    case 'payroll': return 'Payroll';
    case 'credit_card': return 'Credit Card';
    case 'certificate': return 'Certificate';
    case 'deposit': return 'Deposit';
    default: return type;
  }
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function TotalBalanceIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
    </svg>
  );
}

function SpendIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 13l-5 5m0 0l-5-5m5 5V6" />
    </svg>
  );
}

function IncomeIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 11l5-5m0 0l5 5m-5-5v12" />
    </svg>
  );
}

function SavingsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
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

// ---------------------------------------------------------------------------
// AccountGroupSection — renders one category of accounts
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Credit card utilization bar
// ---------------------------------------------------------------------------

function CreditUtilizationBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color =
    pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400">{pct.toFixed(0)}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single account row — renders type-appropriate detail
// ---------------------------------------------------------------------------

function AccountRow({ account }: { account: BankAccountRow }) {
  const balance = parseFloat(String(account.balance));
  const isCreditCard = account.account_type === 'credit_card';
  const isCertificate = account.account_type === 'certificate' || account.account_type === 'deposit';

  const creditLimit = account.credit_limit != null ? parseFloat(String(account.credit_limit)) : null;
  const billedAmount = account.billed_amount != null ? parseFloat(String(account.billed_amount)) : null;
  const unbilledAmount = account.unbilled_amount != null ? parseFloat(String(account.unbilled_amount)) : null;

  return (
    <div className="px-4 py-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-800">
      <div className="flex items-center justify-between">
        {/* Left: bank + masked number + type badge */}
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {account.bank_name}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {account.account_number_masked}
            </span>
          </div>
          <Badge variant={accountTypeBadgeVariant(account.account_type)}>
            {accountTypeLabel(account.account_type)}
          </Badge>
        </div>

        {/* Right: balance */}
        <span className={`text-sm font-semibold tabular-nums ${isCreditCard ? 'text-amber-600 dark:text-amber-400' : 'text-gray-900 dark:text-white'}`}>
          {account.currency} {formatEGP(balance)}
        </span>
      </div>

      {/* Credit card detail row */}
      {isCreditCard && (billedAmount != null || unbilledAmount != null || creditLimit != null) && (
        <div className="mt-2">
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
            {billedAmount != null && (
              <span>Billed: <span className="font-medium text-gray-700 dark:text-gray-300">{account.currency} {formatEGP(billedAmount)}</span></span>
            )}
            {unbilledAmount != null && (
              <span>Unbilled: <span className="font-medium text-gray-700 dark:text-gray-300">{account.currency} {formatEGP(unbilledAmount)}</span></span>
            )}
            {creditLimit != null && (
              <span>Limit: <span className="font-medium text-gray-700 dark:text-gray-300">{account.currency} {formatEGP(creditLimit)}</span></span>
            )}
          </div>
          {creditLimit != null && creditLimit > 0 && (
            <CreditUtilizationBar used={balance} limit={creditLimit} />
          )}
        </div>
      )}

      {/* Certificate / deposit detail row */}
      {isCertificate && (account.interest_rate != null || account.maturity_date != null) && (
        <div className="mt-1.5 flex flex-wrap gap-x-4 text-xs text-gray-500 dark:text-gray-400">
          {account.interest_rate != null && (
            <span>Rate: <span className="font-medium text-emerald-600 dark:text-emerald-400">{(parseFloat(String(account.interest_rate)) * 100).toFixed(2)}%</span></span>
          )}
          {account.maturity_date != null && (
            <span>Matures: <span className="font-medium text-gray-700 dark:text-gray-300">
              {new Intl.DateTimeFormat('en-EG', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(account.maturity_date))}
            </span></span>
          )}
        </div>
      )}
    </div>
  );
}

function AccountGroupSection({ group }: { group: AccountGroup }) {
  if (group.accounts.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">{group.label}</h3>
        <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span>{group.accounts.length} account{group.accounts.length !== 1 ? 's' : ''}</span>
          <span className="font-semibold text-gray-900 dark:text-white">
            EGP {formatEGP(group.totalBalance)}
          </span>
        </div>
      </div>
      <div className="space-y-2">
        {group.accounts.map((account) => (
          <AccountRow key={account.id} account={account} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page (Server Component — data fetched at request time with RLS)
// ---------------------------------------------------------------------------

export default async function DashboardPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [accountsResult, transactionsResult] = await Promise.all([
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
      .limit(600),
  ]);

  const accounts: BankAccountRow[] = accountsResult.data ?? [];
  const allTransactions: TransactionRow[] = transactionsResult.data ?? [];

  // ---------------------------------------------------------------------------
  // Account groups
  // ---------------------------------------------------------------------------

  const standardAccounts = accounts.filter(
    (a) => a.account_type === 'savings' || a.account_type === 'current' || a.account_type === 'payroll',
  );
  const creditCards = accounts.filter((a) => a.account_type === 'credit_card');
  const certificates = accounts.filter(
    (a) => a.account_type === 'certificate' || a.account_type === 'deposit',
  );

  const accountGroups: AccountGroup[] = [
    {
      label: 'Savings, Current & Payroll',
      accounts: standardAccounts,
      totalBalance: standardAccounts.reduce((s, a) => s + parseFloat(String(a.balance)), 0),
    },
    {
      label: 'Credit Cards',
      accounts: creditCards,
      totalBalance: creditCards.reduce((s, a) => s + parseFloat(String(a.balance)), 0),
    },
    {
      label: 'Certificates & Deposits',
      accounts: certificates,
      totalBalance: certificates.reduce((s, a) => s + parseFloat(String(a.balance)), 0),
    },
  ].filter((g) => g.accounts.length > 0);

  // ---------------------------------------------------------------------------
  // KPI computation
  // ---------------------------------------------------------------------------

  // Total liquid balance = savings + current + payroll + certificates (assets)
  // Credit card balances are liabilities — excluded from total balance, shown separately
  const totalBalance = accounts
    .filter((a) => a.account_type !== 'credit_card')
    .reduce((sum, a) => sum + parseFloat(String(a.balance)), 0);

  // Total CC outstanding = sum of CC balances (what you owe)
  const totalCCOutstanding = accounts
    .filter((a) => a.account_type === 'credit_card')
    .reduce((sum, a) => sum + parseFloat(String(a.balance)), 0);

  // Net worth = assets minus CC liabilities
  const netWorth = totalBalance - totalCCOutstanding;

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);

  // Exclude credit card accounts from income/expense KPIs — CC debits/credits
  // are billing events (billed/unbilled amounts already tracked separately),
  // not cash-flow. Count all non-CC credits as income.
  const ccAccountIds = new Set(
    accounts.filter((a) => a.account_type === 'credit_card').map((a) => a.id),
  );

  let monthlyIncome = 0;
  let monthlyExpenses = 0;

  for (const tx of allTransactions) {
    if (tx.transaction_date < monthStart) continue;
    if (ccAccountIds.has(tx.account_id)) continue; // exclude CC statement transactions
    if (tx.transaction_type === 'credit') {
      monthlyIncome += tx.amount;
    } else if (tx.transaction_type === 'debit') {
      monthlyExpenses += tx.amount;
    }
  }

  const netSavings = monthlyIncome - monthlyExpenses;
  const healthScore = computeHealthScore(monthlyIncome, monthlyExpenses, allTransactions.length);
  const spendingCategories = buildSpendingCategories(allTransactions);
  const recentTransactions: Transaction[] = allTransactions.slice(0, 10).map(toTransaction);

  const hasData = accounts.length > 0 || allTransactions.length > 0;

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Overview</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          {hasData
            ? `Your financial snapshot for ${currentMonthLabel()}`
            : 'Connect a bank account in Settings to see your real data'}
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <AccountCard
          label="Total Balance"
          amount={totalBalance}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<TotalBalanceIcon />}
        />
        <AccountCard
          label="Monthly Spend"
          amount={monthlyExpenses}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<SpendIcon />}
        />
        <AccountCard
          label="Monthly Income"
          amount={monthlyIncome}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<IncomeIcon />}
        />
        <AccountCard
          label="Net Savings"
          amount={netSavings}
          currency="EGP"
          trend={netSavings >= 0 ? 'up' : 'down'}
          changePercent={0}
          icon={<SavingsIcon />}
        />
        <AccountCard
          label="Net Worth"
          amount={netWorth}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<NetWorthIcon />}
        />
      </div>

      {/* Accounts grouped by type */}
      {accounts.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">Accounts</h2>
          </CardHeader>
          <CardBody className="space-y-6">
            {accountGroups.map((group) => (
              <AccountGroupSection key={group.label} group={group} />
            ))}
          </CardBody>
        </Card>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SpendingChart categories={spendingCategories} />
        <HealthScore score={healthScore} />
      </div>

      {/* Recent transactions */}
      <RecentTransactions transactions={recentTransactions} />
    </div>
  );
}
