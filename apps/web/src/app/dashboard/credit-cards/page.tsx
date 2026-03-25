import { createClient } from '@/lib/supabase/server';
import { Card, CardBody } from '@/components/ui/card';

export const dynamic = 'force-dynamic';
import { CreditCardSelector } from '@/components/credit-cards/credit-card-selector';
import type { CreditCardData } from '@/components/credit-cards/credit-card-selector';
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

function monthLabel(date: Date): string {
  return new Intl.DateTimeFormat('en-EG', { month: 'short', year: 'numeric' }).format(date);
}

function buildLast6MonthsData(
  transactions: TransactionRow[],
  accountId: string,
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
          tx.account_id === accountId &&
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

function buildPerCardData(
  account: BankAccountRow,
  allTransactions: TransactionRow[],
): CreditCardData {
  const cardTx = allTransactions.filter((tx) => tx.account_id === account.id);

  // Unbilled: current billing cycle (payment_due_date - 27 days)
  const cycleStartDate = (() => {
    const dueDate = account.payment_due_date;
    if (dueDate) {
      const d = new Date(dueDate);
      d.setDate(d.getDate() - 27);
      return d.toISOString().slice(0, 10);
    }
    const fallback = new Date();
    fallback.setDate(fallback.getDate() - 30);
    return fallback.toISOString().slice(0, 10);
  })();

  const unbilledTx = cardTx
    .filter((tx) => tx.transaction_date > cycleStartDate)
    .map(toCardTx);

  const unsettledTx = cardTx
    .filter(
      (tx) =>
        tx.transaction_type === 'unsettled' ||
        tx.description.toLowerCase().includes('pending') ||
        tx.description.toLowerCase().includes('unsettled'),
    )
    .map(toCardTx);

  return {
    id: account.id,
    bank_name: account.bank_name,
    account_number_masked: account.account_number_masked,
    balance: parseFloat(String(account.balance)),
    currency: account.currency,
    is_active: account.is_active,
    billed_amount: account.billed_amount != null ? parseFloat(String(account.billed_amount)) : null,
    unbilled_amount: account.unbilled_amount != null ? parseFloat(String(account.unbilled_amount)) : null,
    credit_limit: account.credit_limit != null ? parseFloat(String(account.credit_limit)) : null,
    minimum_payment: account.minimum_payment != null ? parseFloat(String(account.minimum_payment)) : null,
    payment_due_date: account.payment_due_date ?? null,
    unbilledTx,
    unsettledTx,
    last6MonthsData: buildLast6MonthsData(allTransactions, account.id),
  };
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
      .limit(1000),
  ]);

  const creditCardAccounts: BankAccountRow[] = accountsResult.data ?? [];
  const allTransactions: TransactionRow[] = transactionsResult.data ?? [];

  const totalBalance = creditCardAccounts.reduce(
    (s, a) => s + parseFloat(String(a.balance)),
    0,
  );

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

  const cards: CreditCardData[] = creditCardAccounts.map((account) =>
    buildPerCardData(account, allTransactions),
  );

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

      {/* Card selector + tabs */}
      <CreditCardSelector cards={cards} />
    </div>
  );
}
