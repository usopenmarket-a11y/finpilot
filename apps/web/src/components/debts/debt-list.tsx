'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import type { Debt } from '@/lib/types';

interface DebtListProps {
  debts: Debt[];
  onAddDebt: () => void;
  onRecordPayment: (debt: Debt) => void;
  onEditDebt: (debt: Debt) => void;
  onDeleteDebt: (debtId: string) => void;
  onManagePayments: (debt: Debt) => void;
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'No due date';
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat('en-EG', { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
}

function statusVariant(status: Debt['status']): 'warning' | 'info' | 'success' {
  switch (status) {
    case 'active':
      return 'warning';
    case 'partial':
      return 'info';
    case 'settled':
      return 'success';
  }
}

function isOverdue(dueDate: string | null): boolean {
  if (!dueDate) return false;
  return new Date(dueDate) < new Date();
}

export function DebtList({ debts, onAddDebt, onRecordPayment, onEditDebt, onDeleteDebt, onManagePayments }: DebtListProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (debts.length === 0) {
    return (
      <EmptyState
        title="No debts recorded"
        description="Start tracking money you've lent or borrowed."
        actionLabel="Add Debt"
        onAction={onAddDebt}
        icon={
          <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" />
          </svg>
        }
      />
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {debts.map((debt) => {
        const progressPct = debt.original_amount > 0
          ? Math.min(100, ((debt.original_amount - debt.outstanding_balance) / debt.original_amount) * 100)
          : 0;
        const overdue = isOverdue(debt.due_date) && debt.status !== 'settled';

        // Monthly estimate calculation
        const monthsRemaining = debt.due_date
          ? Math.max(1, Math.ceil((new Date(debt.due_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 30)))
          : null;
        const monthlyEstimate = monthsRemaining !== null && debt.status !== 'settled'
          ? debt.outstanding_balance / monthsRemaining
          : null;

        const isConfirmingDelete = confirmDeleteId === debt.id;

        return (
          <div
            key={debt.id}
            className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 flex flex-col gap-4"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-gray-900 dark:text-white truncate">
                  {debt.counterparty_name}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {debt.debt_type === 'lent' ? 'You lent' : 'You borrowed'}
                  {' · '}
                  <span className={overdue ? 'text-red-500 dark:text-red-400 font-medium' : ''}>
                    Due {formatDate(debt.due_date)}
                  </span>
                  {overdue && (
                    <span className="ml-1 text-red-500 dark:text-red-400 font-medium">(Overdue)</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                {/* Edit button */}
                <button
                  onClick={() => onEditDebt(debt)}
                  className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                  aria-label={`Edit debt with ${debt.counterparty_name}`}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>

                {/* Delete / confirm delete */}
                {isConfirmingDelete ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        onDeleteDebt(debt.id);
                        setConfirmDeleteId(null);
                      }}
                      className="px-2 py-1 rounded-md text-xs font-medium bg-red-500 hover:bg-red-600 text-white transition-colors"
                      aria-label="Confirm delete"
                    >
                      Delete
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(null)}
                      className="px-2 py-1 rounded-md text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                      aria-label="Cancel delete"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteId(debt.id)}
                    className="p-1.5 rounded-md text-gray-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                    aria-label={`Delete debt with ${debt.counterparty_name}`}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                )}

                <Badge variant={debt.debt_type === 'lent' ? 'success' : 'danger'}>
                  {debt.debt_type === 'lent' ? 'Lent' : 'Borrowed'}
                </Badge>
                <Badge variant={statusVariant(debt.status)}>
                  {debt.status.charAt(0).toUpperCase() + debt.status.slice(1)}
                </Badge>
              </div>
            </div>

            {/* Amounts */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Original</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-white mt-0.5 tabular-nums">
                  {debt.currency} {formatEGP(debt.original_amount)}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Outstanding</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-white mt-0.5 tabular-nums">
                  {debt.currency} {formatEGP(debt.outstanding_balance)}
                </p>
              </div>
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-500 dark:text-gray-400">Repaid</span>
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300 tabular-nums">
                  {progressPct.toFixed(0)}%
                </span>
              </div>
              <div className="h-2 w-full bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-brand-500 rounded-full transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                  role="progressbar"
                  aria-valuenow={progressPct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
            </div>

            {/* Monthly estimate */}
            {monthlyEstimate !== null && debt.due_date && (
              <p className="text-xs text-blue-600 dark:text-blue-400 tabular-nums">
                Est. monthly payment:{' '}
                <span className="font-medium">
                  {debt.currency} {formatEGP(monthlyEstimate)}
                </span>
                {' '}
                <span className="text-blue-500 dark:text-blue-500">
                  ({monthsRemaining} {monthsRemaining === 1 ? 'month' : 'months'} remaining)
                </span>
              </p>
            )}

            {/* Notes */}
            {debt.notes && (
              <p className="text-xs text-gray-500 dark:text-gray-400 italic">
                &ldquo;{debt.notes}&rdquo;
              </p>
            )}

            {/* Actions */}
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onManagePayments(debt)}
                className="flex-1"
              >
                Payments
              </Button>
              {debt.status !== 'settled' && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onRecordPayment(debt)}
                  className="flex-1"
                >
                  Record Payment
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
