'use client';

import { useState, useMemo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { recategorizeTransactions } from '@/lib/api-client';
import { createClient } from '@/lib/supabase/client';
import type { Transaction } from '@/lib/types';
import type { AccountOption } from '@/app/dashboard/transactions/page';

interface TransactionTableProps {
  transactions: Transaction[];
  accountOptions?: AccountOption[];
}

const CATEGORY_OPTIONS = [
  { value: '', label: 'All Categories' },
  { value: 'Income', label: 'Income' },
  { value: 'Food & Dining', label: 'Food & Dining' },
  { value: 'Groceries', label: 'Groceries' },
  { value: 'Transportation', label: 'Transportation' },
  { value: 'Shopping', label: 'Shopping' },
  { value: 'Utilities', label: 'Utilities' },
  { value: 'Entertainment', label: 'Entertainment' },
  { value: 'Healthcare', label: 'Healthcare' },
  { value: 'Education', label: 'Education' },
  { value: 'Travel', label: 'Travel' },
  { value: 'Rent & Housing', label: 'Rent & Housing' },
  { value: 'Transfers', label: 'Transfers' },
  { value: 'ATM & Cash', label: 'ATM & Cash' },
  { value: 'Loan Repayment', label: 'Loan Repayment' },
  { value: 'Subscriptions', label: 'Subscriptions' },
  { value: 'Government & Fees', label: 'Government & Fees' },
  { value: 'Insurance', label: 'Insurance' },
  { value: 'Investment', label: 'Investment' },
  { value: 'Other', label: 'Other' },
];

const TYPE_OPTIONS = [
  { value: 'all', label: 'All Types' },
  { value: 'debit', label: 'Debit' },
  { value: 'credit', label: 'Credit' },
];

const PAGE_SIZE = 10;

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat('en-EG', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date);
}

type SortField = 'transaction_date' | 'amount' | 'category';
type SortDir = 'asc' | 'desc';

export function TransactionTable({ transactions, accountOptions = [] }: TransactionTableProps) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [type, setType] = useState('all');
  const [accountId, setAccountId] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [sortField, setSortField] = useState<SortField>('transaction_date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [recategorizing, setRecategorizing] = useState(false);
  const [recatResult, setRecatResult] = useState<string | null>(null);

  async function handleRecategorize() {
    setRecategorizing(true);
    setRecatResult(null);
    try {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      const result = await recategorizeTransactions(user.id);
      setRecatResult(`Done — ${result.updated} of ${result.processed} transactions updated. Refresh to see changes.`);
    } catch {
      setRecatResult('Recategorization failed. Please try again.');
    } finally {
      setRecategorizing(false);
    }
  }

  const accountSelectOptions = useMemo(() => [
    { value: '', label: 'All Accounts' },
    ...accountOptions.map((a) => ({ value: a.id, label: a.label })),
  ], [accountOptions]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return transactions.filter((tx) => {
      if (q && !tx.description.toLowerCase().includes(q) &&
        !tx.category?.toLowerCase().includes(q) &&
        !String(tx.amount).includes(q)) {
        return false;
      }
      if (category && tx.category !== category) return false;
      if (type !== 'all' && tx.transaction_type !== type) return false;
      if (accountId && tx.account_id !== accountId) return false;
      if (dateFrom && tx.transaction_date < dateFrom) return false;
      if (dateTo && tx.transaction_date > dateTo) return false;
      return true;
    });
  }, [transactions, search, category, type, accountId, dateFrom, dateTo]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let aVal: string | number;
      let bVal: string | number;
      if (sortField === 'amount') {
        aVal = a.amount;
        bVal = b.amount;
      } else if (sortField === 'category') {
        aVal = a.category ?? '';
        bVal = b.category ?? '';
      } else {
        aVal = a.transaction_date;
        bVal = b.transaction_date;
      }
      if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filtered, sortField, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paginated = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
    setPage(1);
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) {
      return (
        <svg className="h-3.5 w-3.5 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
        </svg>
      );
    }
    return sortDir === 'asc' ? (
      <svg className="h-3.5 w-3.5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
      </svg>
    ) : (
      <svg className="h-3.5 w-3.5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Filters + Recategorize */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">Filters</p>
          <div className="flex items-center gap-2">
            {recatResult && (
              <p className="text-xs text-gray-500 dark:text-gray-400">{recatResult}</p>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRecategorize}
              disabled={recategorizing}
            >
              {recategorizing ? 'Categorizing…' : 'Re-categorize All'}
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          <Input
            placeholder="Search transactions…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            aria-label="Search transactions"
          />
          {accountOptions.length > 0 && (
            <Select
              options={accountSelectOptions}
              value={accountId}
              onChange={(e) => { setAccountId(e.target.value); setPage(1); }}
              aria-label="Filter by account"
            />
          )}
          <Select
            options={CATEGORY_OPTIONS}
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}
            aria-label="Filter by category"
          />
          <Select
            options={TYPE_OPTIONS}
            value={type}
            onChange={(e) => { setType(e.target.value); setPage(1); }}
            aria-label="Filter by type"
          />
          <div className="flex gap-2">
            <Input
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
              aria-label="Date from"
              className="flex-1"
            />
            <Input
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
              aria-label="Date to"
              className="flex-1"
            />
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
        {paginated.length === 0 ? (
          <EmptyState
            title="No transactions found"
            description="Try adjusting your filters or search query."
            icon={
              <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 dark:border-gray-800">
                <tr>
                  <th
                    className="px-6 py-3 text-left cursor-pointer group"
                    onClick={() => handleSort('transaction_date')}
                  >
                    <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Date <SortIcon field="transaction_date" />
                    </span>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Description
                  </th>
                  <th
                    className="px-6 py-3 text-left cursor-pointer hidden sm:table-cell"
                    onClick={() => handleSort('category')}
                  >
                    <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Category <SortIcon field="category" />
                    </span>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden md:table-cell">
                    Type
                  </th>
                  <th
                    className="px-6 py-3 text-right cursor-pointer"
                    onClick={() => handleSort('amount')}
                  >
                    <span className="flex items-center justify-end gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Amount <SortIcon field="amount" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {paginated.map((tx) => (
                  <tr
                    key={tx.id}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <td className="px-6 py-3.5 whitespace-nowrap text-gray-500 dark:text-gray-400">
                      {formatDate(tx.transaction_date)}
                    </td>
                    <td className="px-6 py-3.5 text-gray-900 dark:text-gray-100 font-medium">
                      {tx.description}
                    </td>
                    <td className="px-6 py-3.5 hidden sm:table-cell">
                      {tx.category ? (
                        <Badge variant="default">{tx.category}</Badge>
                      ) : (
                        <span className="text-gray-400 dark:text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-6 py-3.5 hidden md:table-cell">
                      <Badge variant={tx.transaction_type === 'credit' ? 'success' : 'danger'}>
                        {tx.transaction_type === 'credit' ? 'Credit' : 'Debit'}
                      </Badge>
                    </td>
                    <td className="px-6 py-3.5 text-right whitespace-nowrap">
                      <span
                        className={`font-semibold tabular-nums ${
                          tx.transaction_type === 'credit'
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-500 dark:text-red-400'
                        }`}
                      >
                        {tx.transaction_type === 'credit' ? '+' : '-'} EGP {formatEGP(tx.amount)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {sorted.length > 0 && (
          <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {sorted.length} transaction{sorted.length !== 1 ? 's' : ''}
              {' '}&mdash; Page {page} of {totalPages}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                aria-label="Previous page"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
                Prev
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                aria-label="Next page"
              >
                Next
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
