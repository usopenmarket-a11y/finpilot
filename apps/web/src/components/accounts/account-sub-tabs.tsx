'use client';

import { useState } from 'react';
import type { Database } from '@finpilot/shared';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type TransactionRow = Database['public']['Tables']['transactions']['Row'];

type TabKey = 'details' | 'transactions';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'details', label: 'Account Details' },
  { key: 'transactions', label: 'Transactions' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAmount(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat('en-EG', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(dateStr));
}

// ---------------------------------------------------------------------------
// Credit utilization bar
// ---------------------------------------------------------------------------

function CreditUtilizationBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color = pct >= 90 ? 'bg-negative' : pct >= 70 ? 'bg-warning' : 'bg-positive';
  return (
    <div>
      <div className="flex justify-between text-xs text-ink-muted mb-1">
        <span>Credit utilization</span>
        <span className="font-medium tabular-nums">{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 rounded-full bg-surface-sunken overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail row helper
// ---------------------------------------------------------------------------

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-2 border-b border-line last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-ink-muted">{label}</span>
      <span className="break-words text-sm font-medium text-ink sm:text-right">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AccountDetailsPanel
// ---------------------------------------------------------------------------

function AccountDetailsPanel({ account }: { account: BankAccountRow }) {
  const balance = parseFloat(String(account.balance));
  const isCreditCard = account.account_type === 'credit_card';
  const isCertificate = account.account_type === 'certificate' || account.account_type === 'deposit';

  const creditLimit = account.credit_limit != null ? parseFloat(String(account.credit_limit)) : null;
  const billedAmount = account.billed_amount != null ? parseFloat(String(account.billed_amount)) : null;
  const unbilledAmount = account.unbilled_amount != null ? parseFloat(String(account.unbilled_amount)) : null;
  const minimumPayment = account.minimum_payment != null ? parseFloat(String(account.minimum_payment)) : null;
  const interestRate = account.interest_rate != null ? parseFloat(String(account.interest_rate)) : null;

  return (
    <div className="space-y-4">
      {/* Balance — prominent */}
      <div className="bg-surface-sunken rounded-lg p-4">
        <p className="text-xs text-ink-muted mb-1">
          {isCreditCard ? 'Outstanding Balance' : 'Balance'}
        </p>
        <p className={`break-words text-xl font-semibold tabular-nums font-mono sm:text-2xl ${isCreditCard ? 'text-warning' : 'text-ink'}`}>
          {account.currency} {formatAmount(balance)}
        </p>
      </div>

      {/* Credit card details */}
      {isCreditCard && (
        <div className="space-y-1">
          {creditLimit != null && (
            <DetailRow label="Credit Limit" value={`${account.currency} ${formatAmount(creditLimit)}`} />
          )}
          {billedAmount != null && (
            <DetailRow label="Billed" value={`${account.currency} ${formatAmount(billedAmount)}`} />
          )}
          {unbilledAmount != null && (
            <DetailRow label="Unbilled" value={`${account.currency} ${formatAmount(unbilledAmount)}`} />
          )}
          {minimumPayment != null && (
            <DetailRow label="Minimum Payment" value={`${account.currency} ${formatAmount(minimumPayment)}`} />
          )}
          {account.payment_due_date != null && (
            <DetailRow label="Payment Due" value={formatDate(account.payment_due_date)} />
          )}
          {creditLimit != null && creditLimit > 0 && (
            <div className="pt-2">
              <CreditUtilizationBar used={balance} limit={creditLimit} />
            </div>
          )}
        </div>
      )}

      {/* Certificate / deposit details */}
      {isCertificate && (
        <div className="space-y-1">
          {account.product_name != null && (
            <DetailRow label="Product" value={account.product_name} />
          )}
          {interestRate != null && (
            <DetailRow
              label="Interest Rate"
              value={<span className="text-positive font-mono tabular-nums">{(interestRate * 100).toFixed(2)}%</span>}
            />
          )}
          {account.maturity_date != null && (
            <DetailRow label="Maturity Date" value={formatDate(account.maturity_date)} />
          )}
          {account.opened_date != null && (
            <DetailRow label="Opened" value={formatDate(account.opened_date)} />
          )}
        </div>
      )}

      {/* Standard account details (shown for all types) */}
      <div className="space-y-1">
        <DetailRow label="Bank" value={account.bank_name} />
        <DetailRow label="Account Number" value={account.account_number_masked} />
        <DetailRow label="Currency" value={account.currency} />
        {account.last_synced_at != null && (
          <DetailRow label="Last Synced" value={formatDate(account.last_synced_at)} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AccountTransactionsPanel
// ---------------------------------------------------------------------------

function AccountTransactionsPanel({ transactions }: { transactions: TransactionRow[] }) {
  if (transactions.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-ink-faint">No transactions yet</p>
      </div>
    );
  }

  // Show at most 50 most recent (already sorted desc by date from server)
  const displayed = transactions.slice(0, 50);

  return (
    <div className="divide-y divide-line">
      {displayed.map((tx) => {
        const isCredit = tx.transaction_type === 'credit';
        const amount = parseFloat(String(tx.amount));
        return (
          <div key={tx.id} className="flex items-start justify-between py-2.5 gap-3">
            <div className="flex flex-col min-w-0">
              <span className="text-sm text-ink truncate">
                {tx.description}
              </span>
              <div className="flex flex-wrap items-center gap-2 mt-0.5">
                <span className="text-xs text-ink-faint">
                  {formatDate(tx.transaction_date)}
                </span>
                {tx.category && (
                  <span className="text-xs text-ink-faint">
                    · {tx.category}
                  </span>
                )}
              </div>
            </div>
            <span
              className={`max-w-[45%] text-right text-sm font-semibold tabular-nums font-mono flex-shrink-0 ${
                isCredit ? 'text-positive' : 'text-negative'
              }`}
            >
              {isCredit ? '+' : '-'}{tx.currency} {formatAmount(amount)}
            </span>
          </div>
        );
      })}
      {transactions.length > 50 && (
        <p className="text-xs text-center text-ink-faint py-3">
          Showing 50 of {transactions.length} transactions
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface AccountSubTabsProps {
  account: BankAccountRow;
  transactions: TransactionRow[];
}

export function AccountSubTabs({ account, transactions }: AccountSubTabsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('details');

  return (
    <div className="px-4 pb-4">
      {/* Tab bar */}
      <div className="flex overflow-x-auto border-b border-line mb-4 -mx-4 px-4">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`shrink-0 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab.key
                ? 'border-accent text-accent'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {tab.label}
            {tab.key === 'transactions' && transactions.length > 0 && (
              <span className="ml-1.5 text-xs tabular-nums text-ink-faint">
                ({Math.min(transactions.length, 50)})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'details' && <AccountDetailsPanel account={account} />}
      {activeTab === 'transactions' && <AccountTransactionsPanel transactions={transactions} />}
    </div>
  );
}
