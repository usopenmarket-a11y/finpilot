'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import type { Debt } from '@/lib/types';

interface EditDebtFormProps {
  debt: Debt;
  onSuccess: (debt: Debt) => void;
  onCancel: () => void;
}

interface FormValues {
  counterparty_name: string;
  debt_type: 'lent' | 'borrowed';
  currency: string;
  due_date: string;
  notes: string;
}

interface FormErrors {
  counterparty_name?: string;
}

const DEBT_TYPE_OPTIONS = [
  { value: 'lent', label: 'I lent money' },
  { value: 'borrowed', label: 'I borrowed money' },
];

const CURRENCY_OPTIONS = [
  { value: 'EGP', label: 'EGP — Egyptian Pound' },
  { value: 'USD', label: 'USD — US Dollar' },
  { value: 'EUR', label: 'EUR — Euro' },
];

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {};
  if (!values.counterparty_name.trim()) {
    errors.counterparty_name = 'Name is required';
  }
  return errors;
}

export function EditDebtForm({ debt, onSuccess, onCancel }: EditDebtFormProps) {
  const [values, setValues] = useState<FormValues>({
    counterparty_name: debt.counterparty_name,
    debt_type: debt.debt_type,
    currency: debt.currency,
    due_date: debt.due_date ?? '',
    notes: debt.notes ?? '',
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const set = (field: keyof FormValues) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    setValues((prev) => ({ ...prev, [field]: e.target.value }));
    if (field === 'counterparty_name' && errors.counterparty_name) {
      setErrors((prev) => ({ ...prev, counterparty_name: undefined }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationErrors = validate(values);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    setSubmitting(true);
    setApiError(null);

    try {
      const supabase = createClient();
      const { data, error } = await (supabase as any)
        .from('debts')
        .update({
          counterparty_name: values.counterparty_name.trim(),
          debt_type: values.debt_type,
          currency: values.currency,
          due_date: values.due_date || null,
          notes: values.notes.trim() || null,
        })
        .eq('id', debt.id)
        .select()
        .single();

      if (error) {
        console.error('[EditDebtForm] Supabase update error:', error);
        throw new Error((error as { message: string }).message);
      }
      onSuccess(data as Debt);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <Input
        label="Counterparty Name"
        placeholder="e.g. Ahmed Hassan"
        value={values.counterparty_name}
        onChange={set('counterparty_name')}
        error={errors.counterparty_name}
        required
        autoFocus
      />
      <Select
        label="Type"
        options={DEBT_TYPE_OPTIONS}
        value={values.debt_type}
        onChange={set('debt_type')}
      />
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Original Amount</p>
          <p className="text-sm font-semibold text-gray-900 dark:text-white tabular-nums">
            {debt.currency} {new Intl.NumberFormat('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(debt.original_amount)}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">Cannot be changed</p>
        </div>
        <Select
          label="Currency"
          options={CURRENCY_OPTIONS}
          value={values.currency}
          onChange={set('currency')}
        />
      </div>
      <Input
        label="Due Date"
        type="date"
        value={values.due_date}
        onChange={set('due_date')}
        helperText="Optional"
      />
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300" htmlFor="edit-debt-notes">
          Notes <span className="text-gray-400 dark:text-gray-500 font-normal">(optional)</span>
        </label>
        <textarea
          id="edit-debt-notes"
          rows={3}
          placeholder="Add any relevant details…"
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
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button type="submit" loading={submitting}>
          Save Changes
        </Button>
      </div>
    </form>
  );
}
