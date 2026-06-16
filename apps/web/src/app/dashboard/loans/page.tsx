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
    <div className="rounded-xl border border-line bg-surface overflow-hidden">
      <div className="flex flex-col justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="h-10 w-10 rounded-full bg-negative-soft flex items-center justify-center flex-shrink-0">
            <svg
              className="h-5 w-5 text-negative"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.75}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">
              {account.bank_name}
            </p>
            <p className="mt-0.5 truncate text-xs text-ink-muted">
              <span className="font-mono">{account.account_number_masked}</span>
            </p>
            {credentialLabel && (
              <span className="mt-1 inline-flex max-w-full items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted">
                <span className="truncate">{credentialLabel}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-4 sm:w-auto sm:justify-end sm:gap-6">
          <Badge variant="danger">Loan</Badge>
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-wide text-ink-faint">Outstanding</p>
            <p className="break-words font-mono text-sm font-semibold tabular-nums text-ink">
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
          <h1 className="text-3xl font-semibold tracking-tight text-ink">Loans &amp; Finances</h1>
          <p className="text-sm text-ink-muted mt-1">
            Your outstanding loan and finance balances
          </p>
        </div>
        {accounts.length > 0 && (
          <div className="sm:text-right">
            <p className="text-[11px] uppercase tracking-wide text-ink-faint">Total Outstanding</p>
            <p className="font-mono text-2xl font-semibold text-ink tabular-nums">
              EGP {formatEGP(totalOwed)}
            </p>
          </div>
        )}
      </div>

      {accounts.length === 0 ? (
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-ink-faint mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-lg font-semibold text-ink mb-1">No loans found</p>
            <p className="text-sm text-ink-muted">
              Synced loans and finances will appear here. Run a sync in Settings.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-base font-semibold text-ink">All Loans</h2>
              <span className="text-sm text-ink-muted">
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
