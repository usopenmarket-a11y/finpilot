'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { CreditCardTabs } from './credit-card-tabs';
import type { MonthlySpend, CreditCardTransaction } from './credit-card-tabs';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreditCardData {
  id: string;
  bank_name: string;
  account_number_masked: string;
  balance: number;
  currency: string;
  is_active: boolean;
  billed_amount: number | null;
  unbilled_amount: number | null;
  credit_limit: number | null;
  minimum_payment: number | null;
  payment_due_date: string | null;
  credentialLabel?: string | null;
  // Transactions for this card
  unbilledTx: CreditCardTransaction[];
  unsettledTx: CreditCardTransaction[];
  allCardTx: CreditCardTransaction[];      // BDC: all transactions; NBE: empty
  statementTx: CreditCardTransaction[];
  last6MonthsData: MonthlySpend[];
}

interface CreditCardSelectorProps {
  cards: CreditCardData[];
  fawryRate?: number;
}

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
// Single card row (clickable)
// ---------------------------------------------------------------------------

function CreditCardRow({
  card,
  selected,
  onClick,
}: {
  card: CreditCardData;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full flex flex-col gap-4 px-4 py-4 rounded-xl border transition-colors text-left sm:flex-row sm:items-center sm:justify-between sm:px-5 ${
        selected
          ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20 ring-1 ring-brand-500'
          : 'border-line bg-surface hover:border-gray-300 dark:hover:border-gray-700'
      }`}
    >
      <div className="flex w-full min-w-0 items-center gap-3 sm:w-auto sm:gap-4">
        {/* Card icon */}
        <div className="h-10 w-16 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
          </svg>
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{card.bank_name}</p>
          <p className="text-xs text-ink-muted font-mono mt-0.5">
            {card.account_number_masked}
          </p>
          {card.credentialLabel && (
            <span className="inline-flex items-center gap-1 text-xs bg-surface-sunken text-ink-muted px-2 py-0.5 rounded-full mt-1">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
              </svg>
              {card.credentialLabel}
            </span>
          )}
        </div>
      </div>
      <div className="flex w-full flex-wrap items-center justify-between gap-3 sm:w-auto sm:justify-end sm:gap-6">
        <div className="text-left sm:text-right">
          <p className="text-xs text-ink-muted">Current Balance</p>
          <p className="break-words text-sm font-bold text-ink tabular-nums">
            {card.currency} {formatEGP(card.balance)}
          </p>
        </div>
        <Badge variant="warning">Credit Card</Badge>
        {/* Selection chevron */}
        <svg
          className={`h-4 w-4 flex-shrink-0 transition-transform ${selected ? 'rotate-90 text-accent' : 'text-gray-400'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CreditCardSelector({ cards, fawryRate }: CreditCardSelectorProps) {
  const [selectedId, setSelectedId] = useState<string>('');

  return (
    <div className="space-y-3">
      {cards.map((card) => (
        <div key={card.id}>
          <CreditCardRow
            card={card}
            selected={card.id === selectedId}
            onClick={() => setSelectedId(card.id === selectedId ? '' : card.id)}
          />
          {card.id === selectedId && (
            <div className="mt-2">
              <CreditCardTabs
                last6MonthsData={card.last6MonthsData}
                unbilledTx={card.unbilledTx}
                unsettledTx={card.unsettledTx}
                allCardTx={card.allCardTx}
                statementTx={card.statementTx}
                billedAmount={card.billed_amount}
                creditLimit={card.credit_limit}
                minimumPayment={card.minimum_payment}
                paymentDueDate={card.payment_due_date}
                cardAccountNumber={card.account_number_masked}
                cardIsActive={card.is_active}
                cardBankName={card.bank_name}
                cardBalance={card.balance}
                unbilledAmount={card.unbilled_amount}
                fawryRate={fawryRate}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
