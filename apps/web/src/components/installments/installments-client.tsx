'use client';

import { useState } from 'react';
import { Modal } from '@/components/ui/modal';
import { Card, CardBody } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { createClient } from '@/lib/supabase/client';
import type { Database } from '@finpilot/shared';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type InstallmentRow = Database['public']['Tables']['installments']['Row'];

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'https://finpilot-api-lrfg.onrender.com';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAmount(amount: string | number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(typeof amount === 'string' ? parseFloat(amount) : amount);
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat('en-EG', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(dateStr));
}

function categoryBadgeVariant(
  cat: string,
): 'default' | 'info' | 'warning' | 'success' {
  switch (cat) {
    case 'bnpl': return 'warning';
    case 'property': return 'info';
    case 'vehicle': return 'success';
    default: return 'default';
  }
}

function categoryLabel(cat: string): string {
  switch (cat) {
    case 'bnpl': return 'BNPL';
    case 'property': return 'Property';
    case 'vehicle': return 'Vehicle';
    default: return 'Other';
  }
}

function computeMonthsElapsed(startDate: string, billingDay: number | null): number {
  const start = new Date(startDate);
  const today = new Date();
  let elapsed = (today.getFullYear() - start.getFullYear()) * 12 + (today.getMonth() - start.getMonth());
  if (billingDay != null && today.getDate() < billingDay) {
    elapsed = Math.max(0, elapsed - 1);
  }
  return Math.max(0, elapsed);
}

function nextPaymentDate(startDate: string, totalMonths: number, billingDay: number | null): string | null {
  const elapsed = computeMonthsElapsed(startDate, billingDay);
  if (elapsed >= totalMonths) return null;
  const today = new Date();
  const day = billingDay ?? new Date(startDate).getDate();
  let d: Date;
  try {
    d = new Date(today.getFullYear(), today.getMonth(), day);
  } catch {
    d = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  }
  if (d < today) {
    d = new Date(today.getFullYear(), today.getMonth() + 1, day);
  }
  return d.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

interface FormState {
  name: string;
  category: 'bnpl' | 'property' | 'vehicle' | 'other';
  total_amount: string;
  down_payment: string;
  monthly_amount: string;
  billing_day: string;
  start_date: string;
  total_months: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  category: 'bnpl',
  total_amount: '',
  down_payment: '0',
  monthly_amount: '',
  billing_day: '1',
  start_date: new Date().toISOString().slice(0, 10),
  total_months: '12',
  notes: '',
};

function InstallmentForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial: FormState;
  onSave: (f: FormState) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<FormState>(initial);

  function set(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSave(form);
  }

  const labelCls = 'block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1';
  const inputCls =
    'w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={labelCls}>Name *</label>
        <input
          className={inputCls}
          value={form.name}
          onChange={(e) => set('name', e.target.value)}
          placeholder="e.g. iPhone 15 — Valu"
          required
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Category *</label>
          <select
            className={inputCls}
            value={form.category}
            onChange={(e) => set('category', e.target.value as FormState['category'])}
          >
            <option value="bnpl">BNPL (Valu, etc.)</option>
            <option value="property">Property / Home</option>
            <option value="vehicle">Vehicle</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Total Amount (EGP) *</label>
          <input
            className={inputCls}
            type="number"
            min="0"
            step="0.01"
            value={form.total_amount}
            onChange={(e) => set('total_amount', e.target.value)}
            placeholder="0.00"
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Down Payment (EGP)</label>
          <input
            className={inputCls}
            type="number"
            min="0"
            step="0.01"
            value={form.down_payment}
            onChange={(e) => set('down_payment', e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div>
          <label className={labelCls}>Monthly Amount (EGP) *</label>
          <input
            className={inputCls}
            type="number"
            min="0"
            step="0.01"
            value={form.monthly_amount}
            onChange={(e) => set('monthly_amount', e.target.value)}
            placeholder="0.00"
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className={labelCls}>Start Date *</label>
          <input
            className={inputCls}
            type="date"
            value={form.start_date}
            onChange={(e) => set('start_date', e.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelCls}>Total Months *</label>
          <input
            className={inputCls}
            type="number"
            min="1"
            value={form.total_months}
            onChange={(e) => set('total_months', e.target.value)}
            required
          />
        </div>
        <div>
          <label className={labelCls}>Billing Day</label>
          <input
            className={inputCls}
            type="number"
            min="1"
            max="31"
            value={form.billing_day}
            onChange={(e) => set('billing_day', e.target.value)}
            placeholder="1"
          />
        </div>
      </div>

      <div>
        <label className={labelCls}>Notes</label>
        <textarea
          className={`${inputCls} resize-none`}
          rows={2}
          value={form.notes}
          onChange={(e) => set('notes', e.target.value)}
          placeholder="Optional — merchant name, contract reference, etc."
        />
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 rounded-lg text-sm transition-colors"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium py-2 rounded-lg text-sm hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Installment card
// ---------------------------------------------------------------------------

function InstallmentCard({
  item,
  onEdit,
  onDelete,
}: {
  item: InstallmentRow;
  onEdit: (item: InstallmentRow) => void;
  onDelete: (id: string) => void;
}) {
  const elapsed = computeMonthsElapsed(item.start_date, item.billing_day);
  const remaining = Math.max(0, item.total_months - elapsed);
  const isPaidOff = elapsed >= item.total_months;
  const nextDate = nextPaymentDate(item.start_date, item.total_months, item.billing_day);
  const pct = Math.min(100, (elapsed / item.total_months) * 100);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (!confirm('Delete this installment plan?')) return;
    setDeleting(true);
    onDelete(item.id);
  }

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-gray-900 dark:text-white truncate">
              {item.name}
            </span>
            <Badge variant={categoryBadgeVariant(item.category)}>
              {categoryLabel(item.category)}
            </Badge>
            {isPaidOff && (
              <Badge variant="success">Paid off</Badge>
            )}
          </div>
          {item.notes && (
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">{item.notes}</p>
          )}
        </div>
        <div className="flex gap-1 flex-shrink-0">
          <button
            onClick={() => onEdit(item)}
            className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors"
            title="Edit"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors disabled:opacity-40"
            title="Delete"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Key numbers */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2">
          <p className="text-xs text-gray-500 dark:text-gray-400">Monthly</p>
          <p className="text-sm font-semibold text-gray-900 dark:text-white tabular-nums">
            EGP {formatAmount(item.monthly_amount)}
          </p>
        </div>
        <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2">
          <p className="text-xs text-gray-500 dark:text-gray-400">Remaining</p>
          <p className={`text-sm font-semibold tabular-nums ${isPaidOff ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-900 dark:text-white'}`}>
            {isPaidOff ? '—' : `${remaining} mo`}
          </p>
        </div>
        <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2">
          <p className="text-xs text-gray-500 dark:text-gray-400">Next due</p>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">
            {nextDate ? formatDate(nextDate) : '—'}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-400 dark:text-gray-500 mb-1">
          <span>{elapsed} of {item.total_months} months paid</span>
          <span>{pct.toFixed(0)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          <div
            className={`h-full rounded-full ${isPaidOff ? 'bg-emerald-500' : 'bg-blue-500'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main client component
// ---------------------------------------------------------------------------

interface InstallmentsClientProps {
  initialItems: InstallmentRow[];
}

export function InstallmentsClient({ initialItems }: InstallmentsClientProps) {
  const [items, setItems] = useState<InstallmentRow[]>(initialItems);
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState<InstallmentRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function getUserId(): Promise<string> {
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    return user?.id ?? '';
  }

  async function handleSave(form: FormState) {
    setSaving(true);
    setError(null);
    try {
      const userId = await getUserId();
      const payload = {
        name: form.name,
        category: form.category,
        total_amount: parseFloat(form.total_amount),
        down_payment: parseFloat(form.down_payment || '0'),
        monthly_amount: parseFloat(form.monthly_amount),
        billing_day: form.billing_day ? parseInt(form.billing_day) : null,
        start_date: form.start_date,
        total_months: parseInt(form.total_months),
        notes: form.notes || null,
      };

      if (editItem) {
        const res = await fetch(`${API_BASE}/api/v1/installments/${editItem.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'x-user-id': userId },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        const updated: InstallmentRow = await res.json();
        setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      } else {
        const res = await fetch(`${API_BASE}/api/v1/installments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-user-id': userId },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        const created: InstallmentRow = await res.json();
        setItems((prev) => [created, ...prev]);
      }

      setShowForm(false);
      setEditItem(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    const userId = await getUserId();
    const res = await fetch(`${API_BASE}/api/v1/installments/${id}`, {
      method: 'DELETE',
      headers: { 'x-user-id': userId },
    });
    if (res.ok) {
      setItems((prev) => prev.filter((i) => i.id !== id));
    }
  }

  function handleEdit(item: InstallmentRow) {
    setEditItem(item);
    setShowForm(true);
  }

  function handleCloseForm() {
    setShowForm(false);
    setEditItem(null);
    setError(null);
  }

  const formInitial: FormState = editItem
    ? {
        name: editItem.name,
        category: editItem.category as FormState['category'],
        total_amount: String(editItem.total_amount),
        down_payment: String(editItem.down_payment),
        monthly_amount: String(editItem.monthly_amount),
        billing_day: editItem.billing_day != null ? String(editItem.billing_day) : '1',
        start_date: editItem.start_date,
        total_months: String(editItem.total_months),
        notes: editItem.notes ?? '',
      }
    : EMPTY_FORM;

  // Total monthly obligations
  const totalMonthly = items
    .filter((i) => i.is_active && computeMonthsElapsed(i.start_date, i.billing_day) < i.total_months)
    .reduce((s, i) => s + parseFloat(String(i.monthly_amount)), 0);

  return (
    <div className="space-y-6">
      {/* Summary + add button */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {items.length > 0
              ? `${items.length} plan${items.length !== 1 ? 's' : ''} · EGP ${formatAmount(totalMonthly)}/mo total`
              : 'No installment plans yet'}
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Plan
        </button>
      </div>

      {/* Cards */}
      {items.length === 0 ? (
        <Card>
          <CardBody className="py-16 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
              No installment plans
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Track BNPL purchases, home loans, and other monthly obligations.
            </p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((item) => (
            <InstallmentCard
              key={item.id}
              item={item}
              onEdit={handleEdit}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* Add/Edit modal */}
      <Modal
        open={showForm}
        onClose={handleCloseForm}
        title={editItem ? 'Edit Installment Plan' : 'Add Installment Plan'}
      >
        {error && (
          <p className="mb-3 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
        <InstallmentForm
          initial={formInitial}
          onSave={handleSave}
          onCancel={handleCloseForm}
          saving={saving}
        />
      </Modal>
    </div>
  );
}
