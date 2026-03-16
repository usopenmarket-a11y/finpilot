'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import type { Debt } from '@/lib/types';

interface AddDebtFormProps {
  onSuccess: (debt: Debt) => void;
  onCancel: () => void;
}

interface FormValues {
  counterparty_name: string;
  debt_type: 'lent' | 'borrowed';
  amount: string;
  currency: string;
  due_date: string;
  notes: string;
}

interface FormErrors {
  counterparty_name?: string;
  amount?: string;
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
  const amount = parseFloat(values.amount);
  if (!values.amount || isNaN(amount) || amount <= 0) {
    errors.amount = 'Please enter a valid positive amount';
  }
  return errors;
}

export function AddDebtForm({ onSuccess, onCancel }: AddDebtFormProps) {
  const [values, setValues] = useState<FormValues>({
    counterparty_name: '',
    debt_type: 'lent',
    amount: '',
    currency: 'EGP',
    due_date: '',
    notes: '',
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const set = (field: keyof FormValues) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    setValues((prev) => ({ ...prev, [field]: e.target.value }));
    if (errors[field as keyof FormErrors]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
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
      const payload = {
        counterparty_name: values.counterparty_name.trim(),
        debt_type: values.debt_type,
        original_amount: parseFloat(values.amount),
        currency: values.currency,
        due_date: values.due_date || null,
        notes: values.notes.trim() || null,
      };
      const created = await api.post<Debt>('/debts', payload);
      onSuccess(created);
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
        <Input
          label="Amount"
          type="number"
          min="0.01"
          step="0.01"
          placeholder="0.00"
          value={values.amount}
          onChange={set('amount')}
          error={errors.amount}
          required
        />
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
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300" htmlFor="debt-notes">
          Notes <span className="text-gray-400 dark:text-gray-500 font-normal">(optional)</span>
        </label>
        <textarea
          id="debt-notes"
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
          Add Debt
        </Button>
      </div>
    </form>
  );
}
