'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import { DebtList } from '@/components/debts/debt-list';
import { AddDebtForm } from '@/components/debts/add-debt-form';
import { EditDebtForm } from '@/components/debts/edit-debt-form';
import { PaymentModal } from '@/components/debts/payment-modal';
import { PaymentsManager } from '@/components/debts/payments-manager';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { Debt, DebtPayment } from '@/lib/types';

type ActiveTab = 'borrowing' | 'lending';

export default function DebtsPage() {
  const [debts, setDebts] = useState<Debt[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('lending');
  const [showAddForm, setShowAddForm] = useState(false);
  const [paymentTarget, setPaymentTarget] = useState<Debt | null>(null);
  const [editTarget, setEditTarget] = useState<Debt | null>(null);
  const [paymentsTarget, setPaymentsTarget] = useState<Debt | null>(null);

  const fetchDebts = useCallback(async () => {
    setFetchError(null);
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { setLoading(false); return; }
    const { data, error } = await supabase
      .from('debts')
      .select('*')
      .eq('user_id', user.id)
      .neq('status', 'settled')
      .order('created_at', { ascending: false });
    if (error) {
      console.error('[DebtsPage] fetchDebts error:', error);
      setFetchError(error.message);
      setLoading(false);
      return;
    }
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

  const handleEditDebt = (debt: Debt) => {
    setEditTarget(debt);
  };

  const handleDeleteDebt = async (debtId: string) => {
    const supabase = createClient();
    const { error } = await (supabase as any)
      .from('debts')
      .delete()
      .eq('id', debtId);
    if (error) {
      console.error('[DebtsPage] deleteDebt error:', error);
      return;
    }
    setDebts((prev) => prev.filter((d) => d.id !== debtId));
  };

  const handleEditSuccess = (updated: Debt) => {
    setDebts((prev) => prev.map((d) => d.id === updated.id ? updated : d));
    setEditTarget(null);
  };

  function formatEGP(amount: number): string {
    return new Intl.NumberFormat('en-EG', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(amount);
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink">Debt Tracker</h1>
          <p className="text-sm text-ink-muted mt-1">
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

      {fetchError && (
        <div className="rounded-xl border border-negative/20 bg-negative-soft px-4 py-3">
          <p className="text-sm text-negative font-medium">Failed to load debts</p>
          <p className="text-xs text-negative/80 mt-0.5">{fetchError}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="bg-surface border border-line rounded-xl p-4">
              <p className="text-xs text-ink-muted mb-1">Total to Collect</p>
              <p className="text-xl font-semibold text-positive tabular-nums font-mono">
                EGP {formatEGP(totalLent)}
              </p>
            </div>
            <div className="bg-surface border border-line rounded-xl p-4">
              <p className="text-xs text-ink-muted mb-1">Total Owed</p>
              <p className="text-xl font-semibold text-negative tabular-nums font-mono">
                EGP {formatEGP(totalBorrowed)}
              </p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 overflow-x-auto border-b border-line">
            <button
              onClick={() => setActiveTab('lending')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'lending'
                  ? 'border-accent text-accent'
                  : 'border-transparent text-ink-muted hover:text-ink'
              }`}
            >
              Lending
              <Badge variant="success">{lentDebts.length}</Badge>
            </button>
            <button
              onClick={() => setActiveTab('borrowing')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'borrowing'
                  ? 'border-accent text-accent'
                  : 'border-transparent text-ink-muted hover:text-ink'
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
            onEditDebt={handleEditDebt}
            onDeleteDebt={(debtId) => { void handleDeleteDebt(debtId); }}
            onManagePayments={(debt) => setPaymentsTarget(debt)}
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

      {/* Edit debt modal */}
      <Modal
        open={editTarget !== null}
        onClose={() => setEditTarget(null)}
        title="Edit Debt"
      >
        {editTarget && (
          <EditDebtForm
            debt={editTarget}
            onSuccess={handleEditSuccess}
            onCancel={() => setEditTarget(null)}
          />
        )}
      </Modal>

      {/* Payment modal */}
      <PaymentModal
        debt={paymentTarget}
        open={paymentTarget !== null}
        onClose={() => setPaymentTarget(null)}
        onSuccess={handlePaymentRecorded}
      />

      {/* Payments manager modal */}
      <Modal
        open={paymentsTarget !== null}
        onClose={() => setPaymentsTarget(null)}
        title="Payment History"
      >
        {paymentsTarget && (
          <PaymentsManager
            debt={paymentsTarget}
            onClose={() => setPaymentsTarget(null)}
            onChanged={() => { void fetchDebts(); }}
          />
        )}
      </Modal>
    </div>
  );
}
