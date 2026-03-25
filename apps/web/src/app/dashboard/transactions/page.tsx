import { createClient } from '@/lib/supabase/server';
import { TransactionTable } from '@/components/transactions/transaction-table';

export const dynamic = 'force-dynamic';
import type { Transaction } from '@/lib/types';
import type { Database } from '@finpilot/shared';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];

export interface AccountOption {
  id: string;
  label: string;
}

function toTransaction(row: TransactionRow): Transaction & { account_id: string } {
  return {
    id: row.id,
    description: row.description,
    amount: row.amount,
    transaction_type: row.transaction_type as 'debit' | 'credit',
    transaction_date: row.transaction_date,
    category: row.category,
    currency: row.currency,
    account_id: row.account_id,
  };
}

function accountLabel(account: BankAccountRow): string {
  const typeMap: Record<string, string> = {
    savings: 'Savings',
    current: 'Current',
    payroll: 'Payroll',
    credit_card: 'Credit Card',
    certificate: 'Certificate',
    deposit: 'Deposit',
  };
  const type = typeMap[account.account_type] ?? account.account_type;
  return `${account.bank_name} ${account.account_number_masked} (${type})`;
}

export default async function TransactionsPage() {
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
      .limit(500),
  ]);

  const accounts: BankAccountRow[] = accountsResult.data ?? [];
  const rawTransactions: TransactionRow[] = transactionsResult.data ?? [];

  const transactions = rawTransactions.map(toTransaction);

  const accountOptions: AccountOption[] = accounts.map((a) => ({
    id: a.id,
    label: accountLabel(a),
  }));

  return (
    <div className="p-6 lg:p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Transactions</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Browse and filter your transaction history
        </p>
      </div>
      <TransactionTable transactions={transactions} accountOptions={accountOptions} />
    </div>
  );
}
