'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardBody } from '@/components/ui/card';
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
    case 'credit_card': return 'warning';
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
    case 'credit_card': return 'Credit Card';
    case 'certificate': return 'Certificate';
    case 'deposit': return 'Deposit';
    default: return type;
  }
}

// ---------------------------------------------------------------------------
// Chevron icon
// ---------------------------------------------------------------------------

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-4 w-4 text-gray-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
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
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      await hideAccount(user.id, accountId);
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
      className="p-1.5 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-40 flex-shrink-0"
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
}

function AccordionItem({ account, transactions, isOpen, onToggle, onHide }: AccordionItemProps) {
  const balance = parseFloat(String(account.balance));
  const isCreditCard = account.account_type === 'credit_card';

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      {/* Header — clickable to toggle */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center justify-between bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800/60 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex flex-col min-w-0">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
              {account.bank_name}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {account.account_number_masked}
            </span>
          </div>
          <Badge variant={accountTypeBadgeVariant(account.account_type)}>
            {accountTypeLabel(account.account_type)}
          </Badge>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0 ml-3">
          <span
            className={`text-sm font-semibold tabular-nums ${
              isCreditCard
                ? 'text-amber-600 dark:text-amber-400'
                : 'text-gray-900 dark:text-white'
            }`}
          >
            {account.currency} {formatEGP(balance)}
          </span>
          <HideButton accountId={account.id} onHide={onHide} />
          <ChevronIcon open={isOpen} />
        </div>
      </button>

      {/* Body — sub-tabs */}
      {isOpen && (
        <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
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
  { label: 'Credit Cards', types: ['credit_card'] },
  { label: 'Certificates & Deposits', types: ['certificate', 'deposit'] },
];

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface AccountAccordionProps {
  accounts: BankAccountRow[];
  transactions: TransactionRow[];
}

export function AccountAccordion({ accounts: initialAccounts, transactions }: AccountAccordionProps) {
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  // Open the first account by default
  const [openId, setOpenId] = useState<string | null>(initialAccounts[0]?.id ?? null);

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
      <p className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
        All accounts hidden. They will reappear after the next sync.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.label}>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
            {group.label}
          </h3>
          <div className="space-y-2">
            {group.accounts.map((account) => (
              <AccordionItem
                key={account.id}
                account={account}
                transactions={transactions.filter((t) => t.account_id === account.id)}
                isOpen={openId === account.id}
                onToggle={() => handleToggle(account.id)}
                onHide={handleHide}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
