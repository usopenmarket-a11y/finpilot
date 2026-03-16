import { TransactionTable } from '@/components/transactions/transaction-table';
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
  { id: '9', description: 'Vodafone Bill', amount: 199, transaction_type: 'debit', transaction_date: '2026-03-04', category: 'Utilities', currency: 'EGP' },
  { id: '10', description: 'Coffee & Bakery', amount: 95, transaction_type: 'debit', transaction_date: '2026-03-03', category: 'Food & Dining', currency: 'EGP' },
  { id: '11', description: 'Gym Membership', amount: 350, transaction_type: 'debit', transaction_date: '2026-03-02', category: 'Entertainment', currency: 'EGP' },
  { id: '12', description: 'Gas Station', amount: 280, transaction_type: 'debit', transaction_date: '2026-03-01', category: 'Transport', currency: 'EGP' },
  { id: '13', description: 'Bonus Payment', amount: 5000, transaction_type: 'credit', transaction_date: '2026-02-28', category: 'Income', currency: 'EGP' },
  { id: '14', description: 'Restaurant Dinner', amount: 620, transaction_type: 'debit', transaction_date: '2026-02-27', category: 'Food & Dining', currency: 'EGP' },
  { id: '15', description: 'Internet Bill', amount: 240, transaction_type: 'debit', transaction_date: '2026-02-26', category: 'Utilities', currency: 'EGP' },
  { id: '16', description: 'Clothing Store', amount: 890, transaction_type: 'debit', transaction_date: '2026-02-25', category: 'Shopping', currency: 'EGP' },
  { id: '17', description: 'Taxi Ride', amount: 85, transaction_type: 'debit', transaction_date: '2026-02-24', category: 'Transport', currency: 'EGP' },
  { id: '18', description: 'Cinema Tickets', amount: 160, transaction_type: 'debit', transaction_date: '2026-02-23', category: 'Entertainment', currency: 'EGP' },
  { id: '19', description: 'Supermarket Top-up', amount: 450, transaction_type: 'debit', transaction_date: '2026-02-22', category: 'Food & Dining', currency: 'EGP' },
  { id: '20', description: 'Side Project Payment', amount: 2200, transaction_type: 'credit', transaction_date: '2026-02-21', category: 'Income', currency: 'EGP' },
];

export default function TransactionsPage() {
  return (
    <div className="p-6 lg:p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Transactions</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Browse and filter your transaction history
        </p>
      </div>
      <TransactionTable transactions={MOCK_TRANSACTIONS} />
    </div>
  );
}
