'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Modal } from '@/components/ui/modal';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import type { Debt, DebtPayment } from '@/lib/types';

interface PaymentModalProps {
  debt: Debt | null;
  open: boolean;
  onClose: () => void;
  onSuccess: (payment: DebtPayment) => void;
}

interface FormValues {
  amount: string;
  payment_date: string;
  notes: string;
}

function todayString(): string {
  return new Date().toISOString().split('T')[0] ?? '';
}

interface FormErrors {
  amount?: string;
  payment_date?: string;
}

function validate(values: FormValues, maxAmount: number): FormErrors {
  const errors: FormErrors = {};
  const amount = parseFloat(values.amount);
  if (!values.amount || isNaN(amount) || amount <= 0) {
    errors.amount = 'Please enter a valid positive amount';
  } else if (amount > maxAmount) {
    errors.amount = `Amount cannot exceed outstanding balance (EGP ${maxAmount.toFixed(2)})`;
  }
  if (!values.payment_date) {
    errors.payment_date = 'Payment date is required';
  }
  return errors;
}

export function PaymentModal({ debt, open, onClose, onSuccess }: PaymentModalProps) {
  const [values, setValues] = useState<FormValues>({
    amount: '',
    payment_date: todayString(),
    notes: '',
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const set = (field: keyof FormValues) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    setValues((prev) => ({ ...prev, [field]: e.target.value }));
    if (errors[field as keyof FormErrors]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const handleClose = () => {
    setValues({ amount: '', payment_date: todayString(), notes: '' });
    setErrors({});
    setApiError(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!debt) return;

    const validationErrors = validate(values, debt.outstanding_balance);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    setSubmitting(true);
    setApiError(null);

    try {
      const supabase = createClient();
      const amount = parseFloat(values.amount);

      // Insert payment record
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const { data: payment, error: paymentError } = await (supabase as any)
        .from('debt_payments')
        .insert({
          debt_id: debt.id,
          amount,
          payment_date: values.payment_date,
          notes: values.notes.trim() || null,
        })
        .select()
        .single();

      if (paymentError) throw new Error(paymentError.message);

      // Update debt outstanding_balance and status
      const newBalance = Math.max(0, debt.outstanding_balance - amount);
      const newStatus =
        newBalance === 0
          ? 'settled'
          : newBalance < debt.original_amount
          ? 'partial'
          : debt.status;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const { error: debtError } = await (supabase as any)
        .from('debts')
        .update({
          outstanding_balance: newBalance,
          status: newStatus,
          updated_at: new Date().toISOString(),
        })
        .eq('id', debt.id);

      if (debtError) throw new Error(debtError.message);

      onSuccess(payment as DebtPayment);
      handleClose();
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Failed to record payment. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const title = debt
    ? `Record Payment — ${debt.counterparty_name}`
    : 'Record Payment';

  return (
    <Modal open={open} onClose={handleClose} title={title}>
      {debt && (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Outstanding balance:{' '}
          <span className="font-semibold text-gray-900 dark:text-white">
            {debt.currency} {debt.outstanding_balance.toFixed(2)}
          </span>
        </p>
      )}
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <Input
          label="Payment Amount"
          type="number"
          min="0.01"
          step="0.01"
          placeholder="0.00"
          value={values.amount}
          onChange={set('amount')}
          error={errors.amount}
          required
          autoFocus
        />
        <Input
          label="Payment Date"
          type="date"
          value={values.payment_date}
          onChange={set('payment_date')}
          error={errors.payment_date}
          required
        />
        <div className="flex flex-col gap-1.5">
          <label
            className="text-sm font-medium text-gray-700 dark:text-gray-300"
            htmlFor="payment-notes"
          >
            Notes <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <textarea
            id="payment-notes"
            rows={2}
            placeholder="Add any details about this payment…"
            value={values.notes}
            onChange={set('notes')}
            className="block w-full rounded-lg border border-gray-300 dark:border-gray-700 px-3 py-2 text-sm bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-none"
          />
        </div>

        {apiError && (
          <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
            {apiError}
          </p>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" loading={submitting}>
            Record Payment
          </Button>
        </div>
      </form>
    </Modal>
  );
}
