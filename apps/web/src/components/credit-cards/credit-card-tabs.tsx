'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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
// Repayment category types
// ---------------------------------------------------------------------------

type RepaymentCategory = 'card_payment' | 'fawry_withdrawal' | 'fee' | 'other';

interface ClassifiedTransaction extends CreditCardTransaction {
  repaymentCategory: RepaymentCategory;
}

function classifyTransaction(tx: CreditCardTransaction): RepaymentCategory {
  if (tx.transaction_type === 'credit') return 'card_payment';
  if (tx.description.toLowerCase().includes('fawry')) return 'fawry_withdrawal';
  if (/interest|fee|charge/i.test(tx.description)) return 'fee';
  return 'other';
}

const REPAYMENT_CATEGORY_BADGE: Record<RepaymentCategory, { variant: 'success' | 'info' | 'danger' | 'default'; label: string }> = {
  card_payment:     { variant: 'success', label: 'Card Payment' },
  fawry_withdrawal: { variant: 'info',    label: 'Fawry Withdrawal' },
  fee:              { variant: 'danger',  label: 'Fee / Interest' },
  other:            { variant: 'default', label: 'Other' },
};

// ---------------------------------------------------------------------------
// Repayment Tracker tab panel
// ---------------------------------------------------------------------------

interface RepaymentTrackerPanelProps {
  allCcTx: CreditCardTransaction[];
  billedAmount?: number | null;
}

function RepaymentTrackerPanel({ allCcTx, billedAmount }: RepaymentTrackerPanelProps) {
  const [closingBalanceInput, setClosingBalanceInput] = useState<string>(
    billedAmount != null && billedAmount > 0 ? String(billedAmount) : '',
  );
  const [cashPerCycleInput, setCashPerCycleInput] = useState<string>('');

  // Parse inputs
  const closingBalance = parseFloat(closingBalanceInput) || 0;
  const baseCashAmount = parseFloat(cashPerCycleInput) || 0;

  // Classify all CC transactions
  const classified: ClassifiedTransaction[] = allCcTx.map((tx) => ({
    ...tx,
    repaymentCategory: classifyTransaction(tx),
  }));

  // Sort date-descending for display
  const sortedClassified = [...classified].sort((a, b) =>
    b.transaction_date.localeCompare(a.transaction_date),
  );

  // Aggregates
  const totalPaid = classified
    .filter((tx) => tx.repaymentCategory === 'card_payment')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalFawry = classified
    .filter((tx) => tx.repaymentCategory === 'fawry_withdrawal')
    .reduce((s, tx) => s + tx.amount, 0);

  const totalFees = classified
    .filter((tx) => tx.repaymentCategory === 'fee')
    .reduce((s, tx) => s + tx.amount, 0);

  const remaining = closingBalance - totalPaid;
  const rawProgress = closingBalance > 0 ? (totalPaid / closingBalance) * 100 : 0;
  const progress = Math.min(100, rawProgress);
  const isOverpaid = totalPaid > closingBalance && closingBalance > 0;
  const fawryCost = totalFawry * 0.008;
  const netReduction = totalPaid - fawryCost;
  const recyclingLoops = baseCashAmount > 0 ? Math.floor(totalPaid / baseCashAmount) : 0;

  // Progress bar color: green >= 50%, yellow 25–49%, red < 25%
  const progressBarColor =
    progress >= 50
      ? 'bg-green-500'
      : progress >= 25
      ? 'bg-yellow-500'
      : 'bg-red-500';

  // No balance due state
  if (closingBalance === 0 && closingBalanceInput !== '') {
    return (
      <div className="space-y-6">
        {/* Input row */}
        <InputRow
          closingBalanceInput={closingBalanceInput}
          cashPerCycleInput={cashPerCycleInput}
          onClosingBalanceChange={setClosingBalanceInput}
          onCashPerCycleChange={setCashPerCycleInput}
        />
        <div className="py-10 text-center">
          <p className="text-base font-medium text-gray-600 dark:text-gray-400">
            No balance due
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
            Your closing balance is zero — nothing to repay this cycle.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 1. Input row */}
      <InputRow
        closingBalanceInput={closingBalanceInput}
        cashPerCycleInput={cashPerCycleInput}
        onClosingBalanceChange={setClosingBalanceInput}
        onCashPerCycleChange={setCashPerCycleInput}
      />

      {/* 2. KPI cards — 2×2 grid */}
      <div className="grid grid-cols-2 gap-3">
        <KpiCard
          label="Total Paid"
          value={`EGP ${formatEGP(totalPaid)}`}
          valueColor="text-green-600 dark:text-green-400"
        />
        <KpiCard
          label="Remaining Balance"
          value={`EGP ${formatEGP(Math.max(0, remaining))}`}
          valueColor={remaining > 0 ? 'text-red-500 dark:text-red-400' : 'text-green-600 dark:text-green-400'}
        />
        <KpiCard
          label="Recycling Loops"
          value={String(recyclingLoops)}
          valueColor="text-indigo-600 dark:text-indigo-400"
        />
        <KpiCard
          label="Net Reduction"
          value={`EGP ${formatEGP(netReduction)}`}
          valueColor="text-gray-900 dark:text-white"
        />
      </div>

      {/* 3. Progress bar */}
      {closingBalance > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-gray-700 dark:text-gray-300">
              Repayment Progress
            </span>
            <span className="flex items-center gap-2 font-semibold text-gray-900 dark:text-white">
              {progress.toFixed(1)}% repaid
              {isOverpaid && (
                <Badge variant="warning">Overpaid</Badge>
              )}
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

      {/* 4. Cost breakdown */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
          Cost Breakdown
        </p>
        <div className="grid grid-cols-3 gap-4">
          <CostStat label="Fawry Withdrawals" value={`EGP ${formatEGP(totalFawry)}`} />
          <CostStat
            label="Fawry Cost (0.8%)"
            value={`EGP ${formatEGP(fawryCost)}`}
            valueColor="text-red-500 dark:text-red-400"
          />
          <CostStat
            label="Fees & Interest"
            value={`EGP ${formatEGP(totalFees)}`}
            valueColor={totalFees > 0 ? 'text-red-500 dark:text-red-400' : undefined}
          />
        </div>
      </div>

      {/* 5. Classified transaction table */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
          Classified Transactions ({sortedClassified.length})
        </p>
        {sortedClassified.length === 0 ? (
          <div className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
            No transactions found
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {sortedClassified.map((tx) => {
              const cat = REPAYMENT_CATEGORY_BADGE[tx.repaymentCategory];
              return (
                <div
                  key={tx.id}
                  className="flex items-center justify-between py-3 px-1 gap-3"
                >
                  <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                      {tx.description}
                    </span>
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {formatDate(tx.transaction_date)}
                    </span>
                  </div>
                  <Badge variant={cat.variant}>{cat.label}</Badge>
                  <span
                    className={`text-sm font-semibold tabular-nums flex-shrink-0 ${
                      tx.repaymentCategory === 'card_payment'
                        ? 'text-green-600 dark:text-green-400'
                        : tx.repaymentCategory === 'fawry_withdrawal'
                        ? 'text-blue-600 dark:text-blue-400'
                        : tx.repaymentCategory === 'fee'
                        ? 'text-red-500 dark:text-red-400'
                        : 'text-gray-700 dark:text-gray-300'
                    }`}
                  >
                    {tx.transaction_type === 'credit' ? '+' : '-'} EGP {formatEGP(tx.amount)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Repayment Tracker sub-components
// ---------------------------------------------------------------------------

interface InputRowProps {
  closingBalanceInput: string;
  cashPerCycleInput: string;
  onClosingBalanceChange: (v: string) => void;
  onCashPerCycleChange: (v: string) => void;
}

function InputRow({
  closingBalanceInput,
  cashPerCycleInput,
  onClosingBalanceChange,
  onCashPerCycleChange,
}: InputRowProps) {
  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <Input
            label="Closing Balance (EGP)"
            type="number"
            min="0"
            step="0.01"
            placeholder="e.g. 30000"
            value={closingBalanceInput}
            onChange={(e) => onClosingBalanceChange(e.target.value)}
          />
        </div>
        <div className="flex-1">
          <Input
            label="Cash per Cycle (EGP)"
            type="number"
            min="0"
            step="0.01"
            placeholder="e.g. 5000"
            value={cashPerCycleInput}
            onChange={(e) => onCashPerCycleChange(e.target.value)}
          />
        </div>
      </div>
      <p className="text-xs text-gray-400 dark:text-gray-500">
        These values are not saved — re-enter each visit.
      </p>
    </div>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
  valueColor?: string;
}

function KpiCard({ label, value, valueColor = 'text-gray-900 dark:text-white' }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
      <p className={`text-base font-bold tabular-nums ${valueColor}`}>{value}</p>
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
          />
        )}
      </CardBody>
    </Card>
  );
}
