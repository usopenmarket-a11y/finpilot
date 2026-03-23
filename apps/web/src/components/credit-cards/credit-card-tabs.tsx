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
  last6MonthsData: MonthlySpend[];
  unbilledTx: CreditCardTransaction[];
  unsettledTx: CreditCardTransaction[];
  billedAmount?: number | null;
  creditLimit?: number | null;
  minimumPayment?: number | null;
  paymentDueDate?: string | null;
  // Card Details props
  cardAccountNumber: string;
  cardIsActive: boolean;
  cardBankName: string;
  cardBalance: number;
  unbilledAmount?: number | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type TabKey = 'repayment' | 'unbilled' | 'unsettled' | 'last6' | 'details';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'repayment', label: 'Repayment Tracker' },
  { key: 'unbilled', label: 'Unbilled Transactions' },
  { key: 'unsettled', label: 'Unsettled' },
  { key: 'last6', label: 'Monthly Spend' },
  { key: 'details', label: 'Card Details' },
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
// Fawry breakdown — shared between Unbilled tab and (formerly) Repayment
// ---------------------------------------------------------------------------

interface FawryBreakdownProps {
  transactions: CreditCardTransaction[];
}

function FawryBreakdown({ transactions }: FawryBreakdownProps) {
  const fawryTx = transactions.filter((tx) =>
    tx.description.toUpperCase().includes('MY FAWRY'),
  );

  if (fawryTx.length === 0) return null;

  const totalFawry = fawryTx.reduce((s, tx) => s + tx.amount, 0);
  const fawryCost = totalFawry * 0.008;

  return (
    <div className="mt-6 space-y-3">
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
// Card Details tab panel
// ---------------------------------------------------------------------------

interface CardDetailsPanelProps {
  accountNumber: string;
  isActive: boolean;
  bankName: string;
  balance: number;
  creditLimit: number | null | undefined;
  billedAmount: number | null | undefined;
  unbilledAmount: number | null | undefined;
  minimumPayment: number | null | undefined;
  paymentDueDate: string | null | undefined;
}

function DetailRow({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value != null && value !== '' ? value : null;
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
      {display != null ? (
        <span className="text-sm font-semibold text-gray-900 dark:text-white">{display}</span>
      ) : (
        <span className="text-sm font-semibold text-gray-400 dark:text-gray-600">—</span>
      )}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
      {children}
    </p>
  );
}

function CardDetailsPanel({
  accountNumber,
  isActive,
  bankName,
  balance,
  creditLimit,
  billedAmount,
  unbilledAmount,
  minimumPayment,
  paymentDueDate,
}: CardDetailsPanelProps) {
  const availableCredit =
    creditLimit != null ? creditLimit - balance : null;

  const dueDateDisplay = paymentDueDate
    ? new Intl.DateTimeFormat('en-EG', { day: 'numeric', month: 'short', year: 'numeric' }).format(
        new Date(paymentDueDate),
      )
    : null;

  return (
    <div className="space-y-6">
      {/* Card Info */}
      <div>
        <SectionHeader>Card Info</SectionHeader>
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            <DetailRow label="Card Number" value={accountNumber} />
            <DetailRow label="Bank" value={bankName} />
            <DetailRow label="Card Type" value="Credit Card" />
            <DetailRow label="Product" value={`${bankName} Credit Card`} />
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-gray-500 dark:text-gray-400">Status</span>
              <div>
                {isActive ? (
                  <Badge variant="success">Active</Badge>
                ) : (
                  <Badge variant="warning">Inactive</Badge>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Limits & Balance */}
      <div>
        <SectionHeader>Limits & Balance</SectionHeader>
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            <DetailRow
              label="Credit Limit"
              value={creditLimit != null ? `EGP ${formatEGP(creditLimit)}` : null}
            />
            <DetailRow
              label="Available Credit"
              value={availableCredit != null ? `EGP ${formatEGP(availableCredit)}` : null}
            />
            <DetailRow
              label="Current Balance"
              value={`EGP ${formatEGP(balance)}`}
            />
            <DetailRow
              label="Billed Amount"
              value={billedAmount != null ? `EGP ${formatEGP(billedAmount)}` : null}
            />
            <DetailRow
              label="Unbilled Amount"
              value={unbilledAmount != null ? `EGP ${formatEGP(unbilledAmount)}` : null}
            />
          </div>
        </div>
      </div>

      {/* Payment */}
      <div>
        <SectionHeader>Payment</SectionHeader>
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            <DetailRow
              label="Minimum Payment"
              value={minimumPayment != null ? `EGP ${formatEGP(minimumPayment)}` : null}
            />
            <DetailRow
              label="Payment Due Date"
              value={dueDateDisplay}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CreditCardTabs({
  last6MonthsData,
  unbilledTx,
  unsettledTx,
  billedAmount,
  creditLimit,
  minimumPayment,
  paymentDueDate,
  cardAccountNumber,
  cardIsActive,
  cardBankName,
  cardBalance,
  unbilledAmount,
}: CreditCardTabsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('repayment');

  // Build the full CC transaction set for the repayment tracker — union of all
  // provided transaction arrays, deduped by id.
  const allCcTxMap = new Map<string, CreditCardTransaction>();
  for (const tx of [...unbilledTx, ...unsettledTx]) {
    allCcTxMap.set(tx.id, tx);
  }
  const allCcTx = Array.from(allCcTxMap.values());

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
        {/* Repayment Tracker */}
        {activeTab === 'repayment' && (
          <RepaymentTrackerPanel
            allCcTx={allCcTx}
            billedAmount={billedAmount}
            minimumPayment={minimumPayment}
            paymentDueDate={paymentDueDate}
          />
        )}

        {/* Unbilled Transactions — current month spending + Fawry breakdown */}
        {activeTab === 'unbilled' && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {unbilledTx.length} transaction{unbilledTx.length !== 1 ? 's' : ''}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                Total spend: EGP {formatEGP(totalUnbilled)}
              </p>
            </div>
            <TransactionList transactions={unbilledTx} />
            <FawryBreakdown transactions={unbilledTx} />
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

        {/* Monthly Spend chart */}
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

        {/* Card Details */}
        {activeTab === 'details' && (
          <CardDetailsPanel
            accountNumber={cardAccountNumber}
            isActive={cardIsActive}
            bankName={cardBankName}
            balance={cardBalance}
            creditLimit={creditLimit}
            billedAmount={billedAmount}
            unbilledAmount={unbilledAmount}
            minimumPayment={minimumPayment}
            paymentDueDate={paymentDueDate}
          />
        )}
      </CardBody>
    </Card>
  );
}
