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
  // Transactions for this card
  unbilledTx: CreditCardTransaction[];
  unsettledTx: CreditCardTransaction[];
  last6MonthsData: MonthlySpend[];
}

interface CreditCardSelectorProps {
  cards: CreditCardData[];
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
      className={`w-full flex items-center justify-between px-5 py-4 rounded-xl border transition-colors text-left ${
        selected
          ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20 ring-1 ring-brand-500'
          : 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-700'
      }`}
    >
      <div className="flex items-center gap-4">
        {/* Card icon */}
        <div className="h-10 w-16 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">{card.bank_name}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-0.5">
            {card.account_number_masked}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-6">
        <div className="text-right">
          <p className="text-xs text-gray-500 dark:text-gray-400">Current Balance</p>
          <p className="text-sm font-bold text-gray-900 dark:text-white tabular-nums">
            {card.currency} {formatEGP(card.balance)}
          </p>
        </div>
        <Badge variant="warning">Credit Card</Badge>
        {/* Selection chevron */}
        <svg
          className={`h-4 w-4 flex-shrink-0 transition-transform ${selected ? 'rotate-90 text-brand-500' : 'text-gray-400'}`}
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

export function CreditCardSelector({ cards }: CreditCardSelectorProps) {
  const [selectedId, setSelectedId] = useState<string>(cards[0]?.id ?? '');

  const selectedCard = cards.find((c) => c.id === selectedId) ?? cards[0];

  return (
    <div className="space-y-3">
      {/* Card list — each is a clickable row */}
      <div className="space-y-3">
        {cards.map((card) => (
          <CreditCardRow
            key={card.id}
            card={card}
            selected={card.id === selectedId}
            onClick={() => setSelectedId(card.id)}
          />
        ))}
      </div>

      {/* Tabs for the selected card */}
      {selectedCard && (
        <CreditCardTabs
          last6MonthsData={selectedCard.last6MonthsData}
          unbilledTx={selectedCard.unbilledTx}
          unsettledTx={selectedCard.unsettledTx}
          billedAmount={selectedCard.billed_amount}
          creditLimit={selectedCard.credit_limit}
          minimumPayment={selectedCard.minimum_payment}
          paymentDueDate={selectedCard.payment_due_date}
          cardAccountNumber={selectedCard.account_number_masked}
          cardIsActive={selectedCard.is_active}
          cardBankName={selectedCard.bank_name}
          cardBalance={selectedCard.balance}
          unbilledAmount={selectedCard.unbilled_amount}
        />
      )}
    </div>
  );
}
