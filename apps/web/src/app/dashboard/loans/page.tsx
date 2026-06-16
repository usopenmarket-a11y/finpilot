import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export const dynamic = 'force-dynamic';
import type { Database } from '@finpilot/shared';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type BankCredentialRow = Database['public']['Tables']['bank_credentials']['Row'];

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatCurrency(amount: number, currency: string): string {
  return `${currency} ${formatEGP(amount)}`;
}

const BANK_CODE_TO_NAME: Record<string, string> = {
  NBE: 'National Bank of Egypt',
  CIB: 'Commercial International Bank',
  BDC: 'Banque Du Caire (ibanking)',
  BDC_RETAIL: 'Banque Du Caire (Retail)',
  UB: 'United Bank',
};

function LoanRow({ account, credentialLabel }: { account: BankAccountRow; credentialLabel?: string }) {
  const balance = parseFloat(String(account.balance));
  const owed = balance < 0 ? Math.abs(balance) : balance;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
      <div className="flex flex-col justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="h-10 w-10 rounded-full bg-rose-100 dark:bg-rose-900/30 flex items-center justify-center flex-shrink-0">
            <svg
              className="h-5 w-5 text-rose-600 dark:text-rose-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.75}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">
              {account.bank_name}
            </p>
            <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
              <span className="font-mono">{account.account_number_masked}</span>
            </p>
            {credentialLabel && (
              <span className="mt-1 inline-flex max-w-full items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                <span className="truncate">{credentialLabel}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-4 sm:w-auto sm:justify-end sm:gap-6">
          <Badge variant="danger">Loan</Badge>
          <div className="text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Outstanding</p>
            <p className="break-words text-sm font-bold tabular-nums text-gray-900 dark:text-white">
              {formatCurrency(owed, account.currency)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function LoansPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [{ data }, { data: credData }] = await Promise.all([
    supabase
      .from('bank_accounts')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('account_type', 'loan'),
    supabase
      .from('bank_credentials')
      .select('bank, label')
      .eq('user_id', userId),
  ]);

  const accounts: BankAccountRow[] = data ?? [];

  const bankNameToLabel: Record<string, string> = {};
  for (const cred of ((credData ?? []) as Pick<BankCredentialRow, 'bank' | 'label'>[])) {
    const displayName = BANK_CODE_TO_NAME[cred.bank] ?? cred.bank;
    bankNameToLabel[displayName] = cred.label ?? cred.bank;
  }

  const totalOwed = accounts.reduce((s, a) => {
    const b = parseFloat(String(a.balance));
    return s + (b < 0 ? Math.abs(b) : b);
  }, 0);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Loans &amp; Finances</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Your outstanding loan and finance balances
          </p>
        </div>
        {accounts.length > 0 && (
          <div className="sm:text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Total Outstanding</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">
              EGP {formatEGP(totalOwed)}
            </p>
          </div>
        )}
      </div>

      {accounts.length === 0 ? (
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">No loans found</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Synced loans and finances will appear here. Run a sync in Settings.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">All Loans</h2>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {accounts.length} loan{accounts.length !== 1 ? 's' : ''}
              </span>
            </div>
          </CardHeader>
          <CardBody className="space-y-3">
            {accounts.map((account) => (
              <LoanRow
                key={account.id}
                account={account}
                credentialLabel={bankNameToLabel[account.bank_name]}
              />
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
