import { createClient } from '@/lib/supabase/server';
import { AccountCard } from '@/components/dashboard/account-card';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Database } from '@finpilot/shared';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];

interface AccountGroup {
  label: string;
  accounts: BankAccountRow[];
  totalBalance: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
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

function CCOutstandingIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 13l-5 5m0 0l-5-5m5 5V6" />
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
// Credit utilization bar
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
// Single account row
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

// ---------------------------------------------------------------------------
// Account group section
// ---------------------------------------------------------------------------

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
// Page (Server Component)
// ---------------------------------------------------------------------------

export default async function AccountsPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const { data } = await supabase
    .from('bank_accounts')
    .select('*')
    .eq('user_id', userId)
    .eq('is_active', true);

  const accounts: BankAccountRow[] = data ?? [];

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

  const totalBalance = accounts
    .filter((a) => a.account_type !== 'credit_card')
    .reduce((sum, a) => sum + parseFloat(String(a.balance)), 0);

  const ccOutstanding = accounts
    .filter((a) => a.account_type === 'credit_card')
    .reduce((sum, a) => sum + parseFloat(String(a.balance)), 0);

  const netWorth = totalBalance - ccOutstanding;

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Accounts</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          {accounts.length > 0
            ? `${accounts.length} connected account${accounts.length !== 1 ? 's' : ''} across all banks`
            : 'Connect a bank account in Settings to see your accounts here'}
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <AccountCard
          label="Total Balance"
          amount={totalBalance}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<TotalBalanceIcon />}
        />
        <AccountCard
          label="CC Outstanding"
          amount={ccOutstanding}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<CCOutstandingIcon />}
        />
        <AccountCard
          label="Net Worth"
          amount={netWorth}
          currency="EGP"
          trend={netWorth >= 0 ? 'up' : 'down'}
          changePercent={0}
          icon={<NetWorthIcon />}
        />
      </div>

      {/* Grouped account sections */}
      {accounts.length > 0 ? (
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">All Accounts</h2>
          </CardHeader>
          <CardBody className="space-y-6">
            {accountGroups.map((group) => (
              <AccountGroupSection key={group.label} group={group} />
            ))}
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
              No accounts connected
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Add bank credentials in Settings to start syncing your accounts.
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
