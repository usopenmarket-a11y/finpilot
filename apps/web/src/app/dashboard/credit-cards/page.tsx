import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CreditCardTabs } from '@/components/credit-cards/credit-card-tabs';
import type { MonthlySpend, CreditCardTransaction } from '@/components/credit-cards/credit-card-tabs';
import type { Database } from '@finpilot/shared';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function utilization(balance: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.round((balance / limit) * 100));
}

function utilizationColor(pct: number): string {
  if (pct >= 80) return 'text-red-500 dark:text-red-400';
  if (pct >= 50) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-green-600 dark:text-green-400';
}

function monthLabel(date: Date): string {
  return new Intl.DateTimeFormat('en-EG', { month: 'short', year: 'numeric' }).format(date);
}

function buildLast6MonthsData(
  transactions: TransactionRow[],
  creditCardIds: Set<string>,
): MonthlySpend[] {
  const now = new Date();
  const months: MonthlySpend[] = [];

  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const label = monthLabel(d);
    const start = d.toISOString().slice(0, 10);
    const end = new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);

    const total = transactions
      .filter(
        (tx) =>
          creditCardIds.has(tx.account_id) &&
          tx.transaction_type === 'debit' &&
          tx.transaction_date >= start &&
          tx.transaction_date <= end,
      )
      .reduce((s, tx) => s + tx.amount, 0);

    months.push({ month: label, total });
  }

  return months;
}

function toCardTx(row: TransactionRow): CreditCardTransaction {
  return {
    id: row.id,
    description: row.description,
    amount: row.amount,
    transaction_type: row.transaction_type,
    transaction_date: row.transaction_date,
    category: row.category,
    currency: row.currency,
  };
}

// ---------------------------------------------------------------------------
// Credit card row card
// ---------------------------------------------------------------------------

function CreditCardAccountCard({ account }: { account: BankAccountRow }) {
  const balance = parseFloat(String(account.balance));
  // We don't have a credit_limit field — show balance as current owed amount
  const pct = 0; // cannot compute without limit field

  return (
    <div className="flex items-center justify-between px-5 py-4 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
      <div className="flex items-center gap-4">
        {/* Card icon */}
        <div className="h-10 w-16 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">{account.bank_name}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-0.5">
            {account.account_number_masked}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-6">
        <div className="text-right">
          <p className="text-xs text-gray-500 dark:text-gray-400">Current Balance</p>
          <p className="text-sm font-bold text-gray-900 dark:text-white tabular-nums">
            {account.currency} {formatEGP(balance)}
          </p>
        </div>
        {pct > 0 && (
          <div className="text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Utilization</p>
            <p className={`text-sm font-bold tabular-nums ${utilizationColor(pct)}`}>
              {pct}%
            </p>
          </div>
        )}
        <Badge variant="warning">Credit Card</Badge>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function CreditCardsPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [accountsResult, transactionsResult] = await Promise.all([
    supabase
      .from('bank_accounts')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('account_type', 'credit_card'),
    supabase
      .from('transactions')
      .select('*')
      .eq('user_id', userId)
      .order('transaction_date', { ascending: false })
      .limit(500),
  ]);

  const creditCardAccounts: BankAccountRow[] = accountsResult.data ?? [];
  const allTransactions: TransactionRow[] = transactionsResult.data ?? [];

  const creditCardIds = new Set(creditCardAccounts.map((a) => a.id));
  const creditCardTx = allTransactions.filter((tx) => creditCardIds.has(tx.account_id));

  // Current month transactions
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
  const currentMonthTx = creditCardTx
    .filter((tx) => tx.transaction_date >= monthStart)
    .map(toCardTx);

  // Last 6 months monthly spend
  const last6MonthsData = buildLast6MonthsData(allTransactions, creditCardIds);

  // Unbilled: transaction_type = 'unbilled' OR in current month (proxy)
  const unbilledTx = creditCardTx
    .filter(
      (tx) =>
        tx.transaction_type === 'unbilled' ||
        tx.transaction_date >= monthStart,
    )
    .map(toCardTx);

  // Unsettled: transaction_type = 'unsettled' OR description contains 'pending'/'unsettled'
  const unsettledTx = creditCardTx
    .filter(
      (tx) =>
        tx.transaction_type === 'unsettled' ||
        tx.description.toLowerCase().includes('pending') ||
        tx.description.toLowerCase().includes('unsettled'),
    )
    .map(toCardTx);

  const totalBalance = creditCardAccounts.reduce(
    (s, a) => s + parseFloat(String(a.balance)),
    0,
  );

  // Extract billed_amount and credit_limit from the first CC account for the
  // Repayment Tracker tab pre-fill
  const firstCcAccount = creditCardAccounts[0] ?? null;
  const billedAmount: number | null =
    firstCcAccount?.billed_amount != null
      ? parseFloat(String(firstCcAccount.billed_amount))
      : null;
  const creditLimit: number | null =
    firstCcAccount?.credit_limit != null
      ? parseFloat(String(firstCcAccount.credit_limit))
      : null;
  const minimumPayment: number | null =
    firstCcAccount?.minimum_payment != null
      ? parseFloat(String(firstCcAccount.minimum_payment))
      : null;
  const paymentDueDate: string | null = firstCcAccount?.payment_due_date ?? null;

  if (creditCardAccounts.length === 0) {
    return (
      <div className="p-6 lg:p-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Credit Cards</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Manage and monitor your credit card activity
          </p>
        </div>
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
              No credit cards connected
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Add a credit card account in Settings to track your spending here.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Credit Cards</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Manage and monitor your credit card activity
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-gray-500 dark:text-gray-400">Total Outstanding</p>
          <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">
            EGP {formatEGP(totalBalance)}
          </p>
        </div>
      </div>

      {/* Card list */}
      <div className="space-y-3">
        {creditCardAccounts.map((account) => (
          <CreditCardAccountCard key={account.id} account={account} />
        ))}
      </div>

      {/* Tabs */}
      <CreditCardTabs
        currentMonthTx={currentMonthTx}
        last6MonthsData={last6MonthsData}
        unbilledTx={unbilledTx}
        unsettledTx={unsettledTx}
        billedAmount={billedAmount}
        creditLimit={creditLimit}
        minimumPayment={minimumPayment}
        paymentDueDate={paymentDueDate}
      />
    </div>
  );
}
