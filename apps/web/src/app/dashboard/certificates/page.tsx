import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export const dynamic = 'force-dynamic';
import type { Database } from '@finpilot/shared';

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

function formatCurrency(amount: number, currency: string): string {
  return `${currency} ${formatEGP(amount)}`;
}

function typeLabel(type: string): string {
  switch (type) {
    case 'certificate': return 'Certificate of Deposit';
    case 'deposit': return 'Term Deposit';
    case 'term_deposit': return 'Term Deposit';
    default: return type;
  }
}

function typeBadgeVariant(type: string): 'danger' | 'info' | 'warning' {
  switch (type) {
    case 'certificate': return 'danger';
    case 'deposit':
    case 'term_deposit': return 'info';
    default: return 'warning';
  }
}

// ---------------------------------------------------------------------------
// Certificate account row
// ---------------------------------------------------------------------------

function daysUntil(dateStr: string): number {
  const target = new Date(dateStr);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-EG', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function durationLabel(openedStr: string, maturityStr: string): string {
  const opened = new Date(openedStr);
  const maturity = new Date(maturityStr);
  const totalDays = Math.round((maturity.getTime() - opened.getTime()) / (1000 * 60 * 60 * 24));
  const months = Math.round(totalDays / 30.44);
  if (months >= 12 && months % 12 === 0) return `${months / 12} year${months / 12 > 1 ? 's' : ''}`;
  if (months >= 12) return `${Math.floor(months / 12)}y ${months % 12}m`;
  return `${months} month${months !== 1 ? 's' : ''}`;
}

function CertificateRow({ account }: { account: BankAccountRow }) {
  const balance = parseFloat(String(account.balance));
  const interestRate = account.interest_rate != null ? parseFloat(String(account.interest_rate)) : null;
  const maturityDate = account.maturity_date ?? null;
  const openedDate = account.opened_date ?? null;
  const productName = account.product_name ?? null;
  const remainingDays = maturityDate ? daysUntil(maturityDate) : null;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Main row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-5 py-4">
        <div className="flex items-center gap-4">
          {/* Icon */}
          <div className="h-10 w-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center flex-shrink-0">
            <svg
              className="h-5 w-5 text-amber-600 dark:text-amber-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.75}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
            </svg>
          </div>

          <div>
            <p className="text-sm font-semibold text-gray-900 dark:text-white">
              {productName ?? account.bank_name}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {account.bank_name} · <span className="font-mono">{account.account_number_masked}</span>
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 sm:gap-6">
          <Badge variant={typeBadgeVariant(account.account_type)}>
            {typeLabel(account.account_type)}
          </Badge>
          {interestRate != null && (
            <div className="text-right">
              <p className="text-xs text-gray-500 dark:text-gray-400">Interest Rate</p>
              <p className="text-sm font-bold text-amber-600 dark:text-amber-400 tabular-nums">
                {(interestRate * 100).toFixed(2)}%
              </p>
            </div>
          )}
          <div className="text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Principal</p>
            <p className="text-sm font-bold text-gray-900 dark:text-white tabular-nums">
              {formatCurrency(balance, account.currency)}
            </p>
          </div>
        </div>
      </div>

      {/* Detail row */}
      {(openedDate || maturityDate) && (
        <div className="flex flex-wrap gap-x-6 gap-y-2 px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400">
          {openedDate && (
            <span>
              Opened: <span className="font-medium text-gray-700 dark:text-gray-200">{formatDate(openedDate)}</span>
            </span>
          )}
          {openedDate && maturityDate && (
            <span>
              Duration: <span className="font-medium text-gray-700 dark:text-gray-200">{durationLabel(openedDate, maturityDate)}</span>
            </span>
          )}
          {maturityDate && (
            <span>
              Matures: <span className="font-medium text-gray-700 dark:text-gray-200">{formatDate(maturityDate)}</span>
            </span>
          )}
          {remainingDays != null && remainingDays > 0 && (
            <span>
              Remaining: <span className={`font-medium ${remainingDays <= 30 ? 'text-red-500 dark:text-red-400' : 'text-gray-700 dark:text-gray-200'}`}>
                {remainingDays} day{remainingDays !== 1 ? 's' : ''}
              </span>
            </span>
          )}
          {remainingDays != null && remainingDays <= 0 && (
            <span className="font-medium text-green-600 dark:text-green-400">Matured</span>
          )}
          {interestRate != null && maturityDate && openedDate && (
            <span>
              Est. profit: <span className="font-medium text-amber-600 dark:text-amber-400 tabular-nums">
                {formatCurrency(
                  balance * interestRate * (Math.round((new Date(maturityDate).getTime() - new Date(openedDate).getTime()) / (1000 * 60 * 60 * 24)) / 365),
                  account.currency
                )}
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function CertificatesPage() {
  const supabase = await createClient();

  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const { data } = await supabase
    .from('bank_accounts')
    .select('*')
    .eq('user_id', userId)
    .eq('is_active', true)
    .in('account_type', ['certificate', 'deposit', 'term_deposit']);

  const accounts: BankAccountRow[] = data ?? [];

  const totalValue = accounts.reduce((s, a) => s + parseFloat(String(a.balance)), 0);

  // Group by currency for the summary
  const byCurrency: Record<string, number> = {};
  for (const a of accounts) {
    byCurrency[a.currency] = (byCurrency[a.currency] ?? 0) + parseFloat(String(a.balance));
  }

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Certificates &amp; Deposits
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Your fixed-income savings instruments
          </p>
        </div>
        {accounts.length > 0 && (
          <div className="text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Total Value</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">
              EGP {formatEGP(totalValue)}
            </p>
          </div>
        )}
      </div>

      {accounts.length === 0 ? (
        /* Empty state */
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
              No certificates or deposits found
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Add a certificate or deposit account in Settings to track them here.
            </p>
          </CardBody>
        </Card>
      ) : (
        <>
          {/* Summary by currency */}
          {Object.keys(byCurrency).length > 1 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {Object.entries(byCurrency).map(([currency, total]) => (
                <div
                  key={currency}
                  className="bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800 rounded-xl px-4 py-3"
                >
                  <p className="text-xs text-amber-700 dark:text-amber-400 font-medium mb-1">
                    {currency}
                  </p>
                  <p className="text-lg font-bold text-amber-900 dark:text-amber-300 tabular-nums">
                    {formatEGP(total)}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Account list */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-gray-900 dark:text-white">
                  All Instruments
                </h2>
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  {accounts.length} account{accounts.length !== 1 ? 's' : ''}
                </span>
              </div>
            </CardHeader>
            <CardBody className="space-y-3">
              {accounts.map((account) => (
                <CertificateRow key={account.id} account={account} />
              ))}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
