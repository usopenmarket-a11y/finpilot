'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { AccountSubTabs } from './account-sub-tabs';
import { hideAccount } from '@/lib/api-client';
import { createClient } from '@/lib/supabase/client';
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

function accountTypeBadgeVariant(
  type: string,
): 'default' | 'success' | 'info' | 'warning' | 'danger' {
  switch (type) {
    case 'savings': return 'success';
    case 'current': return 'default';
    case 'payroll': return 'info';
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
    case 'certificate': return 'Certificate';
    case 'deposit': return 'Deposit';
    default: return type;
  }
}

function accountGradient(type: string): string {
  switch (type) {
    case 'savings': return 'from-emerald-500 to-teal-600';
    case 'current': return 'from-blue-500 to-blue-600';
    case 'payroll': return 'from-violet-500 to-purple-600';
    case 'certificate':
    case 'deposit': return 'from-amber-500 to-orange-500';
    default: return 'from-gray-400 to-gray-500';
  }
}

// ---------------------------------------------------------------------------
// Chevron icon
// ---------------------------------------------------------------------------

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-4 w-4 text-ink-faint transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Hide button
// ---------------------------------------------------------------------------

function HideButton({ accountId, onHide }: { accountId: string; onHide: (id: string) => void }) {
  const [hiding, setHiding] = useState(false);

  async function handleHide(e: React.MouseEvent) {
    e.stopPropagation(); // don't toggle accordion
    if (hiding) return;
    setHiding(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const accessToken = session?.access_token;
      if (!accessToken) return;
      await hideAccount(accessToken, accountId);
      onHide(accountId);
    } catch (err) {
      console.error('Failed to hide account', err);
    } finally {
      setHiding(false);
    }
  }

  return (
    <button
      onClick={handleHide}
      disabled={hiding}
      title="Hide account (reappears on next sync)"
      className="p-1.5 rounded text-ink-faint hover:text-negative hover:bg-negative-soft transition-colors disabled:opacity-40 flex-shrink-0"
    >
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
      </svg>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Single accordion item
// ---------------------------------------------------------------------------

interface AccordionItemProps {
  account: BankAccountRow;
  transactions: TransactionRow[];
  isOpen: boolean;
  onToggle: () => void;
  onHide: (id: string) => void;
  credentialLabel?: string;
}

function AccordionItem({ account, transactions, isOpen, onToggle, onHide, credentialLabel }: AccordionItemProps) {
  const balance = parseFloat(String(account.balance));

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className={`w-full flex flex-col gap-4 px-4 py-4 rounded-xl border transition-colors text-left sm:flex-row sm:items-center sm:justify-between sm:px-5 ${
          isOpen
            ? 'border-accent bg-accent-soft ring-1 ring-accent'
            : 'border-line bg-surface hover:border-line-strong'
        }`}
      >
        <div className="flex w-full min-w-0 items-center gap-3 sm:w-auto sm:gap-4">
          <div className={`h-10 w-16 rounded-md bg-gradient-to-br ${accountGradient(account.account_type)} flex items-center justify-center flex-shrink-0`}>
            <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">
              {account.bank_name}
            </p>
            <p className="text-xs text-ink-muted font-mono mt-0.5">
              {account.account_number_masked}
            </p>
            {credentialLabel && (
              <span className="mt-1 inline-flex max-w-full items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted">
                <svg className="h-3 w-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
                <span className="truncate">{credentialLabel}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-3 sm:w-auto sm:justify-end sm:gap-4">
          <div className="text-left sm:text-right">
            <p className="text-xs text-ink-muted">Balance</p>
            <p className="break-words text-sm font-semibold text-ink tabular-nums font-mono">
              {account.currency} {formatEGP(balance)}
            </p>
          </div>
          <Badge variant={accountTypeBadgeVariant(account.account_type)}>
            {accountTypeLabel(account.account_type)}
          </Badge>
          <HideButton accountId={account.id} onHide={onHide} />
          <ChevronIcon open={isOpen} />
        </div>
      </button>

      {isOpen && (
        <div className="mt-2 border border-line rounded-xl overflow-hidden bg-surface">
          <AccountSubTabs account={account} transactions={transactions} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group section
// ---------------------------------------------------------------------------

const GROUP_CONFIGS: { label: string; types: string[] }[] = [
  { label: 'Savings, Current & Payroll', types: ['savings', 'current', 'payroll'] },
];

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface AccountAccordionProps {
  accounts: BankAccountRow[];
  transactions: TransactionRow[];
  credentialLabels?: Record<string, string>;
}

export function AccountAccordion({ accounts: initialAccounts, transactions, credentialLabels = {} }: AccountAccordionProps) {
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);

  const visibleAccounts = initialAccounts.filter((a) => !hiddenIds.has(a.id));

  function handleHide(id: string) {
    setHiddenIds((prev) => new Set([...prev, id]));
    if (openId === id) setOpenId(null);
  }

  function handleToggle(id: string) {
    setOpenId((prev) => (prev === id ? null : id));
  }

  const groups = GROUP_CONFIGS.map(({ label, types }) => ({
    label,
    accounts: visibleAccounts.filter((a) => types.includes(a.account_type)),
  })).filter((g) => g.accounts.length > 0);

  if (groups.length === 0) {
    return (
      <p className="text-sm text-ink-muted py-4 text-center">
        All accounts hidden. They will reappear after the next sync.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.label}>
          <h3 className="text-sm font-semibold text-ink-muted mb-3 uppercase tracking-wider text-xs">
            {group.label}
          </h3>
          <div className="space-y-3">
            {group.accounts.map((account) => (
              <AccordionItem
                key={account.id}
                account={account}
                transactions={transactions.filter((t) => t.account_id === account.id)}
                isOpen={openId === account.id}
                onToggle={() => handleToggle(account.id)}
                onHide={handleHide}
                credentialLabel={account.credential_label ?? credentialLabels[account.bank_name]}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
