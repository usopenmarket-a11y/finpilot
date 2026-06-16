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

function PrepaidCardRow({
  account,
  credentialLabel,
}: {
  account: BankAccountRow;
  credentialLabel?: string;
}) {
  const balance = parseFloat(String(account.balance));

  return (
    <div className="rounded-xl border border-line bg-surface overflow-hidden">
      <div className="flex flex-col justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="h-10 w-10 rounded-full bg-info-soft flex items-center justify-center flex-shrink-0">
            <svg
              className="h-5 w-5 text-info"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.75}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h4m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
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
          <Badge variant="info">Prepaid</Badge>
          <div className="text-right">
            <p className="text-xs text-ink-muted">Balance</p>
            <p className="break-words font-mono text-sm font-semibold tabular-nums text-ink">
              {formatCurrency(balance, account.currency)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function PrepaidCardsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [{ data }, { data: credData }] = await Promise.all([
    supabase
      .from('bank_accounts')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('account_type', 'prepaid_card'),
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

  const totalBalance = accounts.reduce((s, a) => s + parseFloat(String(a.balance)), 0);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink">Prepaid Cards</h1>
          <p className="text-sm text-ink-muted mt-1">
            Your prepaid card balances
          </p>
        </div>
        {accounts.length > 0 && (
          <div className="sm:text-right">
            <p className="text-xs text-ink-muted">Total Balance</p>
            <p className="font-mono text-2xl font-semibold text-ink tabular-nums">
              EGP {formatEGP(totalBalance)}
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
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h4m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            <p className="text-base font-medium text-ink mb-1">
              No prepaid cards found
            </p>
            <p className="text-sm text-ink-muted">
              Synced prepaid cards will appear here. Run a sync in Settings.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-base font-semibold text-ink">
                All Prepaid Cards
              </h2>
              <span className="text-sm text-ink-muted">
                {accounts.length} card{accounts.length !== 1 ? 's' : ''}
              </span>
            </div>
          </CardHeader>
          <CardBody className="space-y-3">
            {accounts.map((account) => (
              <PrepaidCardRow
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
