'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import { DebtList } from '@/components/debts/debt-list';
import { AddDebtForm } from '@/components/debts/add-debt-form';
import { PaymentModal } from '@/components/debts/payment-modal';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { Debt, DebtPayment } from '@/lib/types';

type ActiveTab = 'borrowing' | 'lending';

export default function DebtsPage() {
  const [debts, setDebts] = useState<Debt[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ActiveTab>('lending');
  const [showAddForm, setShowAddForm] = useState(false);
  const [paymentTarget, setPaymentTarget] = useState<Debt | null>(null);

  const fetchDebts = useCallback(async () => {
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { setLoading(false); return; }
    const { data } = await supabase
      .from('debts')
      .select('*')
      .eq('user_id', user.id)
      .neq('status', 'settled')
      .order('created_at', { ascending: false });
    setDebts((data ?? []) as Debt[]);
    setLoading(false);
  }, []);

  useEffect(() => { void fetchDebts(); }, [fetchDebts]);

  const lentDebts = debts.filter((d) => d.debt_type === 'lent');
  const borrowedDebts = debts.filter((d) => d.debt_type === 'borrowed');
  const visibleDebts = activeTab === 'lending' ? lentDebts : borrowedDebts;

  const totalLent = lentDebts.reduce((s, d) => s + d.outstanding_balance, 0);
  const totalBorrowed = borrowedDebts.reduce((s, d) => s + d.outstanding_balance, 0);

  const handleDebtAdded = (debt: Debt) => {
    setDebts((prev) => [debt, ...prev]);
    setShowAddForm(false);
  };

  const handlePaymentRecorded = (_payment: DebtPayment) => {
    setPaymentTarget(null);
    // Refetch so outstanding_balance and status are accurate from DB
    void fetchDebts();
  };

  function formatEGP(amount: number): string {
    return new Intl.NumberFormat('en-EG', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(amount);
  }

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Debt Tracker</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Track money you&apos;ve lent and borrowed
          </p>
        </div>
        <Button onClick={() => setShowAddForm(true)} size="sm">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Debt
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Total to Collect</p>
              <p className="text-xl font-bold text-green-600 dark:text-green-400 tabular-nums">
                EGP {formatEGP(totalLent)}
              </p>
            </div>
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Total Owed</p>
              <p className="text-xl font-bold text-red-500 dark:text-red-400 tabular-nums">
                EGP {formatEGP(totalBorrowed)}
              </p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200 dark:border-gray-800 gap-1">
            <button
              onClick={() => setActiveTab('lending')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'lending'
                  ? 'border-brand-500 text-brand-500'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              }`}
            >
              Lending
              <Badge variant="success">{lentDebts.length}</Badge>
            </button>
            <button
              onClick={() => setActiveTab('borrowing')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'borrowing'
                  ? 'border-brand-500 text-brand-500'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              }`}
            >
              Borrowing
              <Badge variant="danger">{borrowedDebts.length}</Badge>
            </button>
          </div>

          {/* Debt list */}
          <DebtList
            debts={visibleDebts}
            onAddDebt={() => setShowAddForm(true)}
            onRecordPayment={(debt) => setPaymentTarget(debt)}
          />
        </>
      )}

      {/* Add debt modal */}
      <Modal
        open={showAddForm}
        onClose={() => setShowAddForm(false)}
        title="Add New Debt"
      >
        <AddDebtForm
          onSuccess={handleDebtAdded}
          onCancel={() => setShowAddForm(false)}
        />
      </Modal>

      {/* Payment modal */}
      <PaymentModal
        debt={paymentTarget}
        open={paymentTarget !== null}
        onClose={() => setPaymentTarget(null)}
        onSuccess={handlePaymentRecorded}
      />
    </div>
  );
}
