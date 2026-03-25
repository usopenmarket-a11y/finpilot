import { createClient } from '@/lib/supabase/server';
import { AccountCard } from '@/components/dashboard/account-card';
import { Card, CardBody } from '@/components/ui/card';
import { AccountAccordion } from '@/components/accounts/account-accordion';
import type { Database } from '@finpilot/shared';


export const dynamic = 'force-dynamic';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
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

function CertificateIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
    </svg>
  );
}

function AccountCountIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Page (Server Component)
// ---------------------------------------------------------------------------

export default async function AccountsPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [{ data: accountData }, { data: txData }] = await Promise.all([
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

  const accounts: BankAccountRow[] = accountData ?? [];
  const transactions = txData ?? [];

  // ---------------------------------------------------------------------------
  // KPI computation
  // ---------------------------------------------------------------------------

  const bankAccounts = accounts.filter(
    (a) => ['savings', 'current', 'payroll'].includes(a.account_type),
  );
  const certAccounts = accounts.filter(
    (a) => ['certificate', 'deposit'].includes(a.account_type),
  );

  const liquidBalance = bankAccounts.reduce(
    (sum, a) => sum + parseFloat(String(a.balance)), 0,
  );
  const certBalance = certAccounts.reduce(
    (sum, a) => sum + parseFloat(String(a.balance)), 0,
  );
  const totalBalance = liquidBalance + certBalance;

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Accounts</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          {(bankAccounts.length + certAccounts.length) > 0
            ? `${bankAccounts.length + certAccounts.length} account${(bankAccounts.length + certAccounts.length) !== 1 ? 's' : ''} across all banks`
            : 'Connect a bank account in Settings to see your accounts here'}
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <AccountCard
          label="Liquid Balance"
          amount={liquidBalance}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<TotalBalanceIcon />}
        />
        <AccountCard
          label="Certificates & Deposits"
          amount={certBalance}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<CertificateIcon />}
        />
        <AccountCard
          label="Total Account Balance"
          amount={totalBalance}
          currency="EGP"
          trend="neutral"
          changePercent={0}
          icon={<AccountCountIcon />}
        />
      </div>

      {/* Account accordion — pass only non-CC accounts */}
      {(bankAccounts.length + certAccounts.length) > 0 ? (
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-4">All Accounts</h2>
          <AccountAccordion accounts={[...bankAccounts, ...certAccounts]} transactions={transactions} />
        </div>
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
