'use client';

import React, { useState } from 'react';
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
  billedAmount?: number | null;
  creditLimit?: number | null;
  minimumPayment?: number | null;
  paymentDueDate?: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type TabKey = 'current' | 'last6' | 'unbilled' | 'unsettled' | 'repayment';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'current', label: 'Current Month' },
  { key: 'last6', label: 'Last 6 Months' },
  { key: 'unbilled', label: 'Unbilled' },
  { key: 'unsettled', label: 'Unsettled' },
  { key: 'repayment', label: 'Repayment Tracker' },
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
// Repayment Tracker tab panel
// ---------------------------------------------------------------------------

interface RepaymentTrackerPanelProps {
  allCcTx: CreditCardTransaction[];
  billedAmount?: number | null;
  minimumPayment?: number | null;
  paymentDueDate?: string | null;
}

function RepaymentTrackerPanel({
  allCcTx,
  billedAmount,
  minimumPayment,
  paymentDueDate,
}: RepaymentTrackerPanelProps) {
  const closingBalance = billedAmount ?? 0;

  // Total amounts paid = sum of all credit transactions
  const totalPaid = allCcTx
    .filter((tx) => tx.transaction_type === 'credit')
    .reduce((s, tx) => s + tx.amount, 0);

  // Fawry withdrawals — description contains "MY FAWRY"
  const fawryTx = allCcTx.filter((tx) =>
    tx.description.toUpperCase().includes('MY FAWRY'),
  );
  const totalFawry = fawryTx.reduce((s, tx) => s + tx.amount, 0);

  // Fawry interest cost = total_fawry * 0.008
  const fawryCost = totalFawry * 0.008;

  // Remaining = closing balance - total paid
  const remaining = closingBalance - totalPaid;
  const isOverpaid = totalPaid > closingBalance && closingBalance > 0;

  // Progress
  const rawProgress = closingBalance > 0 ? (totalPaid / closingBalance) * 100 : 0;
  const progress = Math.min(100, rawProgress);
  const progressBarColor =
    progress >= 50 ? 'bg-green-500' : progress >= 25 ? 'bg-yellow-500' : 'bg-red-500';

  // Format payment due date
  const dueDateDisplay = paymentDueDate
    ? new Intl.DateTimeFormat('en-EG', { day: 'numeric', month: 'short', year: 'numeric' }).format(
        new Date(paymentDueDate),
      )
    : null;

  return (
    <div className="space-y-6">
      {/* Statement header row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          label="Closing Balance"
          value={closingBalance > 0 ? `EGP ${formatEGP(closingBalance)}` : '—'}
          valueColor="text-gray-900 dark:text-white"
        />
        <KpiCard
          label="Minimum Payment"
          value={
            minimumPayment != null && minimumPayment > 0
              ? `EGP ${formatEGP(minimumPayment)}`
              : '—'
          }
          valueColor="text-yellow-600 dark:text-yellow-400"
        />
        <KpiCard
          label="Total Paid"
          value={`EGP ${formatEGP(totalPaid)}`}
          valueColor="text-green-600 dark:text-green-400"
        />
        <KpiCard
          label="Remaining"
          value={`EGP ${formatEGP(Math.max(0, remaining))}`}
          valueColor={
            isOverpaid
              ? 'text-green-600 dark:text-green-400'
              : remaining > 0
              ? 'text-red-500 dark:text-red-400'
              : 'text-green-600 dark:text-green-400'
          }
          badge={isOverpaid ? <Badge variant="success">Overpaid</Badge> : null}
        />
      </div>

      {/* Payment due date */}
      {dueDateDisplay && (
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <span>Payment due: <span className="font-semibold text-gray-900 dark:text-white">{dueDateDisplay}</span></span>
        </div>
      )}

      {/* Progress bar */}
      {closingBalance > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-gray-700 dark:text-gray-300">Repayment Progress</span>
            <span className="font-semibold text-gray-900 dark:text-white">
              {progress.toFixed(1)}% repaid
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${progressBarColor}`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Fawry breakdown */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
          Fawry Breakdown
        </p>
        <div className="grid grid-cols-2 gap-4">
          <CostStat
            label="MY FAWRY CAIRO EGY total"
            value={`EGP ${formatEGP(totalFawry)}`}
          />
          <CostStat
            label="Fawry interest (0.8%)"
            value={`EGP ${formatEGP(fawryCost)}`}
            valueColor="text-red-500 dark:text-red-400"
          />
        </div>
      </div>

      {/* Fawry transaction list */}
      {fawryTx.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
            MY FAWRY CAIRO EGY Transactions ({fawryTx.length})
          </p>
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {[...fawryTx]
              .sort((a, b) => b.transaction_date.localeCompare(a.transaction_date))
              .map((tx) => (
                <div key={tx.id} className="flex items-center justify-between py-3 px-1 gap-3">
                  <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                      {tx.description}
                    </span>
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {formatDate(tx.transaction_date)}
                    </span>
                  </div>
                  <span className="text-sm font-semibold tabular-nums text-blue-600 dark:text-blue-400 flex-shrink-0">
                    - EGP {formatEGP(tx.amount)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {closingBalance === 0 && (
        <div className="py-10 text-center">
          <p className="text-base font-medium text-gray-600 dark:text-gray-400">
            No balance due
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
            Sync your account to load closing balance and payment details.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Repayment Tracker sub-components
// ---------------------------------------------------------------------------

interface KpiCardProps {
  label: string;
  value: string;
  valueColor?: string;
  badge?: React.ReactNode;
}

function KpiCard({ label, value, valueColor = 'text-gray-900 dark:text-white', badge }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <p className={`text-base font-bold tabular-nums ${valueColor}`}>{value}</p>
        {badge}
      </div>
    </div>
  );
}

interface CostStatProps {
  label: string;
  value: string;
  valueColor?: string;
}

function CostStat({ label, value, valueColor = 'text-gray-900 dark:text-white' }: CostStatProps) {
  return (
    <div className="text-center">
      <p className={`text-sm font-semibold tabular-nums ${valueColor}`}>{value}</p>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</p>
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
  billedAmount,
  creditLimit,
  minimumPayment,
  paymentDueDate,
}: CreditCardTabsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('current');

  // Combine all CC transactions available for the repayment tracker
  // Use currentMonthTx as the base — the page passes all CC tx through this prop set.
  // The repayment tracker needs the full set passed via a dedicated prop; for now
  // we derive it from the union of all provided transaction arrays, deduped by id.
  const allCcTxMap = new Map<string, CreditCardTransaction>();
  for (const tx of [...currentMonthTx, ...unbilledTx, ...unsettledTx]) {
    allCcTxMap.set(tx.id, tx);
  }
  const allCcTx = Array.from(allCcTxMap.values());

  const totalCurrent = currentMonthTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalUnbilled = unbilledTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalUnsettled = unsettledTx
    .filter((tx) => tx.transaction_type === 'debit')
    .reduce((s, tx) => s + tx.amount, 0);

  // creditLimit is available for future utilization display — currently unused in UI
  void creditLimit;

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

        {/* Repayment Tracker */}
        {activeTab === 'repayment' && (
          <RepaymentTrackerPanel
            allCcTx={allCcTx}
            billedAmount={billedAmount}
            minimumPayment={minimumPayment}
            paymentDueDate={paymentDueDate}
          />
        )}
      </CardBody>
    </Card>
  );
}
