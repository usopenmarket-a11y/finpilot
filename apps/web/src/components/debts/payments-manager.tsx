'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import type { Debt, DebtPayment } from '@/lib/types';

export interface PaymentsManagerProps {
  debt: Debt;
  onClose: () => void;
  onChanged: () => void;
}

function formatAmount(amount: number): string {
  return new Intl.NumberFormat('en-EG', { minimumFractionDigits: 2 }).format(amount);
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat('en-EG', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(dateStr));
}

interface EditState {
  amount: string;
  payment_date: string;
  notes: string;
}

interface RowErrors {
  amount?: string;
}

export function PaymentsManager({ debt, onClose, onChanged }: PaymentsManagerProps) {
  const [payments, setPayments] = useState<DebtPayment[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Per-row edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<EditState>({ amount: '', payment_date: '', notes: '' });
  const [editErrors, setEditErrors] = useState<RowErrors>({});
  const [savingId, setSavingId] = useState<string | null>(null);

  // Per-row delete confirm
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);

  const fetchPayments = useCallback(async () => {
    setFetchError(null);
    const supabase = createClient();
    const { data, error } = await (supabase as unknown as {
      from: (table: string) => {
        select: (cols: string) => {
          eq: (col: string, val: string) => {
            order: (col: string, opts: { ascending: boolean }) => Promise<{ data: DebtPayment[] | null; error: { message: string } | null }>;
          };
        };
      };
    })
      .from('debt_payments')
      .select('*')
      .eq('debt_id', debt.id)
      .order('payment_date', { ascending: false });

    if (error) {
      setFetchError(error.message);
      setLoading(false);
      return;
    }
    setPayments(data ?? []);
    setLoading(false);
  }, [debt.id]);

  useEffect(() => {
    void fetchPayments();
  }, [fetchPayments]);

  // ── Helpers ──────────────────────────────────────────────────────────────

  /** Re-sum all payments then derive outstanding_balance and status for the debt. */
  async function recalcDebt(): Promise<{ outstanding_balance: number; status: Debt['status'] }> {
    const supabase = createClient();
    const { data } = await (supabase as unknown as {
      from: (table: string) => {
        select: (cols: string) => {
          eq: (col: string, val: string) => Promise<{ data: { amount: number }[] | null; error: unknown }>;
        };
      };
    })
      .from('debt_payments')
      .select('amount')
      .eq('debt_id', debt.id);

    const totalPaid = (data ?? []).reduce((sum, p) => sum + p.amount, 0);
    const outstanding = Math.max(0, debt.original_amount - totalPaid);
    const status: Debt['status'] =
      outstanding === 0
        ? 'settled'
        : outstanding < debt.original_amount
        ? 'partial'
        : 'active';
    return { outstanding_balance: outstanding, status };
  }

  async function updateDebt(fields: { outstanding_balance: number; status: Debt['status'] }) {
    const supabase = createClient();
    await (supabase as unknown as {
      from: (table: string) => {
        update: (data: Record<string, unknown>) => {
          eq: (col: string, val: string) => Promise<{ error: { message: string } | null }>;
        };
      };
    })
      .from('debts')
      .update(fields)
      .eq('id', debt.id);
  }

  // ── Delete ────────────────────────────────────────────────────────────────

  async function handleDelete(payment: DebtPayment) {
    setDeletingId(payment.id);
    setActionError(null);
    try {
      const supabase = createClient();
      const { error: delError } = await (supabase as unknown as {
        from: (table: string) => {
          delete: () => {
            eq: (col: string, val: string) => Promise<{ error: { message: string } | null }>;
          };
        };
      })
        .from('debt_payments')
        .delete()
        .eq('id', payment.id);

      if (delError) throw new Error(delError.message);

      // Recompute: add the deleted payment amount back then re-sum from DB
      // (fetchPayments hasn't run yet so we remove from local state first)
      setPayments((prev) => prev.filter((p) => p.id !== payment.id));

      const fields = await recalcDebt();
      await updateDebt(fields);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Delete failed. Please try again.');
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  // ── Edit ──────────────────────────────────────────────────────────────────

  function startEdit(payment: DebtPayment) {
    setEditingId(payment.id);
    setEditValues({
      amount: String(payment.amount),
      payment_date: payment.payment_date,
      notes: payment.notes ?? '',
    });
    setEditErrors({});
    setConfirmDeleteId(null);
    setActionError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditErrors({});
  }

  async function handleSaveEdit(payment: DebtPayment) {
    const amount = parseFloat(editValues.amount);
    if (isNaN(amount) || amount <= 0) {
      setEditErrors({ amount: 'Amount must be greater than 0' });
      return;
    }

    setSavingId(payment.id);
    setActionError(null);
    try {
      const supabase = createClient();
      const { error: updateError } = await (supabase as unknown as {
        from: (table: string) => {
          update: (data: Record<string, unknown>) => {
            eq: (col: string, val: string) => Promise<{ error: { message: string } | null }>;
          };
        };
      })
        .from('debt_payments')
        .update({
          amount,
          payment_date: editValues.payment_date,
          notes: editValues.notes.trim() || null,
        })
        .eq('id', payment.id);

      if (updateError) throw new Error(updateError.message);

      // Update local list optimistically before recalc
      setPayments((prev) =>
        prev.map((p) =>
          p.id === payment.id
            ? {
                ...p,
                amount,
                payment_date: editValues.payment_date,
                notes: editValues.notes.trim() || null,
              }
            : p,
        ),
      );
      setEditingId(null);

      const fields = await recalcDebt();
      await updateDebt(fields);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Save failed. Please try again.');
    } finally {
      setSavingId(null);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400">
        Failed to load payments: {fetchError}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Debt summary line */}
      <p className="text-sm text-gray-500 dark:text-gray-400">
        <span className="font-medium text-gray-900 dark:text-white">{debt.counterparty_name}</span>
        {' — '}
        {debt.currency} {formatAmount(debt.original_amount)} original &bull; {debt.currency}{' '}
        {formatAmount(debt.outstanding_balance)} outstanding
      </p>

      {actionError && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {actionError}
        </div>
      )}

      {payments.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">
          No payments recorded
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {payments.map((payment) => {
            const isEditing = editingId === payment.id;
            const isConfirmDelete = confirmDeleteId === payment.id;
            const isDeleting = deletingId === payment.id;
            const isSaving = savingId === payment.id;

            return (
              <li
                key={payment.id}
                className="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50 overflow-hidden"
              >
                {/* Normal row */}
                {!isEditing && (
                  <div className="flex items-start justify-between gap-3 px-4 py-3">
                    <div className="flex flex-col gap-0.5 min-w-0">
                      <span className="text-sm font-semibold text-gray-900 dark:text-white tabular-nums">
                        {debt.currency} {formatAmount(payment.amount)}
                      </span>
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {formatDate(payment.payment_date)}
                      </span>
                      {payment.notes && (
                        <span className="text-xs text-gray-400 dark:text-gray-500 italic truncate">
                          &ldquo;{payment.notes}&rdquo;
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {isConfirmDelete ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => { void handleDelete(payment); }}
                            disabled={isDeleting}
                            className="px-2 py-1 rounded-md text-xs font-medium bg-red-500 hover:bg-red-600 text-white transition-colors disabled:opacity-50"
                            aria-label="Confirm delete payment"
                          >
                            {isDeleting ? 'Deleting…' : 'Delete'}
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            disabled={isDeleting}
                            className="px-2 py-1 rounded-md text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
                            aria-label="Cancel delete"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <>
                          {/* Edit icon */}
                          <button
                            onClick={() => startEdit(payment)}
                            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                            aria-label="Edit payment"
                          >
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                            </svg>
                          </button>
                          {/* Delete icon */}
                          <button
                            onClick={() => setConfirmDeleteId(payment.id)}
                            className="p-1.5 rounded-md text-gray-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                            aria-label="Delete payment"
                          >
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* Inline edit form */}
                {isEditing && (
                  <div className="px-4 py-3 flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-3">
                      <Input
                        label="Amount"
                        type="number"
                        min="0.01"
                        step="0.01"
                        placeholder="0.00"
                        value={editValues.amount}
                        onChange={(e) => {
                          setEditValues((prev) => ({ ...prev, amount: e.target.value }));
                          if (editErrors.amount) setEditErrors({});
                        }}
                        error={editErrors.amount}
                        required
                        autoFocus
                      />
                      <Input
                        label="Date"
                        type="date"
                        value={editValues.payment_date}
                        onChange={(e) =>
                          setEditValues((prev) => ({ ...prev, payment_date: e.target.value }))
                        }
                        required
                      />
                    </div>
                    <Input
                      label="Notes"
                      placeholder="Optional note"
                      value={editValues.notes}
                      onChange={(e) =>
                        setEditValues((prev) => ({ ...prev, notes: e.target.value }))
                      }
                    />
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={cancelEdit}
                        disabled={isSaving}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        loading={isSaving}
                        onClick={() => { void handleSaveEdit(payment); }}
                      >
                        Save
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex justify-end pt-1">
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}
