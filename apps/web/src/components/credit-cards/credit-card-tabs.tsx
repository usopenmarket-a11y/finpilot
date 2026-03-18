'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { CreditCardSpendChart } from '@/components/charts/credit-card-spend-chart';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreditCardTransaction {
  id: string;
  description: string;
  amount: number;
  transaction_type: string;
  transaction_date: string;
  category: string | null;
  currency: string;
}

export interface MonthlySpend {
  month: string;
  total: number;
}

interface CreditCardTabsProps {
  currentMonthTx: CreditCardTransaction[];
  last6MonthsData: MonthlySpend[];
  unbilledTx: CreditCardTransaction[];
  unsettledTx: CreditCardTransaction[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type TabKey = 'current' | 'last6' | 'unbilled' | 'unsettled';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'current', label: 'Current Month' },
  { key: 'last6', label: 'Last 6 Months' },
  { key: 'unbilled', label: 'Unbilled' },
  { key: 'unsettled', label: 'Unsettled' },
];

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat('en-EG', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(dateStr));
}

// ---------------------------------------------------------------------------
// Transaction list shared across tabs
// ---------------------------------------------------------------------------

function TransactionList({ transactions }: { transactions: CreditCardTransaction[] }) {
  if (transactions.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-gray-400 dark:text-gray-500">
        No transactions found
      </div>
    );
  }

  return (
    <div className="divide-y divide-gray-100 dark:divide-gray-800">
      {transactions.map((tx) => (
        <div key={tx.id} className="flex items-center justify-between py-3 px-1">
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
              {tx.description}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {formatDate(tx.transaction_date)}
              </span>
              {tx.category && (
                <Badge variant="default">{tx.category}</Badge>
              )}
            </div>
          </div>
          <span
            className={`text-sm font-semibold tabular-nums ml-4 flex-shrink-0 ${
              tx.transaction_type === 'credit'
                ? 'text-green-600 dark:text-green-400'
                : 'text-red-500 dark:text-red-400'
            }`}
          >
            {tx.transaction_type === 'credit' ? '+' : '-'} EGP {formatEGP(tx.amount)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CreditCardTabs({
  currentMonthTx,
  last6MonthsData,
  unbilledTx,
  unsettledTx,
}: CreditCardTabsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('current');

  const totalCurrent = currentMonthTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalUnbilled = unbilledTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalUnsettled = unsettledTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  return (
    <Card>
      {/* Tab bar */}
      <div className="border-b border-gray-200 dark:border-gray-800">
        <div className="flex overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-brand-500 text-brand-500'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              }`}
              aria-selected={activeTab === tab.key}
              role="tab"
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <CardBody>
        {/* Current Month */}
        {activeTab === 'current' && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {currentMonthTx.length} transaction{currentMonthTx.length !== 1 ? 's' : ''}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                Total spend: EGP {formatEGP(totalCurrent)}
              </p>
            </div>
            <TransactionList transactions={currentMonthTx} />
          </div>
        )}

        {/* Last 6 Months chart */}
        {activeTab === 'last6' && (
          <div>
            <CardHeader className="px-0 pt-0 pb-4 border-b-0">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                Monthly Spend — Last 6 Months
              </h3>
            </CardHeader>
            <CreditCardSpendChart data={last6MonthsData} />
            <div className="mt-4 divide-y divide-gray-100 dark:divide-gray-800">
              {last6MonthsData.map((m) => (
                <div key={m.month} className="flex justify-between py-2 text-sm">
                  <span className="text-gray-600 dark:text-gray-400">{m.month}</span>
                  <span className="font-semibold tabular-nums text-gray-900 dark:text-white">
                    EGP {formatEGP(m.total)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Unbilled */}
        {activeTab === 'unbilled' && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {unbilledTx.length} transaction{unbilledTx.length !== 1 ? 's' : ''}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                Total: EGP {formatEGP(totalUnbilled)}
              </p>
            </div>
            <TransactionList transactions={unbilledTx} />
          </div>
        )}

        {/* Unsettled */}
        {activeTab === 'unsettled' && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {unsettledTx.length} transaction{unsettledTx.length !== 1 ? 's' : ''}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                Total: EGP {formatEGP(totalUnsettled)}
              </p>
            </div>
            <TransactionList transactions={unsettledTx} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
