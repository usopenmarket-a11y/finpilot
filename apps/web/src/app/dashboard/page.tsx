import { AccountCard } from '@/components/dashboard/account-card';
import { SpendingChart } from '@/components/dashboard/spending-chart';
import { RecentTransactions } from '@/components/dashboard/recent-transactions';
import { HealthScore } from '@/components/dashboard/health-score';
import type { Transaction } from '@/lib/types';

const MOCK_TRANSACTIONS: Transaction[] = [
  { id: '1', description: 'Carrefour Supermarket', amount: 850, transaction_type: 'debit', transaction_date: '2026-03-14', category: 'Food & Dining', currency: 'EGP' },
  { id: '2', description: 'Salary Deposit', amount: 15000, transaction_type: 'credit', transaction_date: '2026-03-01', category: 'Income', currency: 'EGP' },
  { id: '3', description: 'Uber Trip', amount: 120, transaction_type: 'debit', transaction_date: '2026-03-13', category: 'Transport', currency: 'EGP' },
  { id: '4', description: 'Netflix Subscription', amount: 149, transaction_type: 'debit', transaction_date: '2026-03-10', category: 'Entertainment', currency: 'EGP' },
  { id: '5', description: 'Electricity Bill', amount: 430, transaction_type: 'debit', transaction_date: '2026-03-08', category: 'Utilities', currency: 'EGP' },
  { id: '6', description: 'Amazon Purchase', amount: 650, transaction_type: 'debit', transaction_date: '2026-03-07', category: 'Shopping', currency: 'EGP' },
  { id: '7', description: 'ATM Withdrawal', amount: 2000, transaction_type: 'debit', transaction_date: '2026-03-06', category: 'Cash', currency: 'EGP' },
  { id: '8', description: 'Freelance Payment', amount: 3500, transaction_type: 'credit', transaction_date: '2026-03-05', category: 'Income', currency: 'EGP' },
];

const SPENDING_CATEGORIES = [
  { name: 'Food & Dining', amount: 850, color: '#f59e0b' },
  { name: 'Cash', amount: 2000, color: '#8b5cf6' },
  { name: 'Shopping', amount: 650, color: '#3b82f6' },
  { name: 'Utilities', amount: 430, color: '#06b6d4' },
  { name: 'Entertainment', amount: 149, color: '#ec4899' },
  { name: 'Transport', amount: 120, color: '#22c55e' },
];

function TotalBalanceIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
    </svg>
  );
}

function SpendIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 13l-5 5m0 0l-5-5m5 5V6" />
    </svg>
  );
}

function IncomeIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 11l5-5m0 0l5 5m-5-5v12" />
    </svg>
  );
}

function SavingsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

export default function DashboardPage() {
  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Overview</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Your financial snapshot for March 2026
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <AccountCard
          label="Total Balance"
          amount={42350}
          currency="EGP"
          trend="up"
          changePercent={4.2}
          icon={<TotalBalanceIcon />}
        />
        <AccountCard
          label="Monthly Spend"
          amount={4199}
          currency="EGP"
          trend="down"
          changePercent={8.1}
          icon={<SpendIcon />}
        />
        <AccountCard
          label="Monthly Income"
          amount={18500}
          currency="EGP"
          trend="up"
          changePercent={2.3}
          icon={<IncomeIcon />}
        />
        <AccountCard
          label="Net Savings"
          amount={14301}
          currency="EGP"
          trend="up"
          changePercent={12.5}
          icon={<SavingsIcon />}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SpendingChart categories={SPENDING_CATEGORIES} />
        <HealthScore score={74} />
      </div>

      {/* Recent transactions */}
      <RecentTransactions transactions={MOCK_TRANSACTIONS} />
    </div>
  );
}
