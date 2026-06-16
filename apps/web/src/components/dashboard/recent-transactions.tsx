import Link from 'next/link';
import { Card, CardHeader, CardBody } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Transaction } from '@/lib/types';

interface RecentTransactionsProps {
  transactions: Transaction[];
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat('en-EG', { month: 'short', day: 'numeric' }).format(date);
}

function categoryBadgeVariant(category: string | null): 'default' | 'success' | 'warning' | 'info' {
  switch (category) {
    case 'Income':
      return 'success';
    case 'Food & Dining':
      return 'warning';
    case 'Transport':
      return 'info';
    default:
      return 'default';
  }
}

export function RecentTransactions({ transactions }: RecentTransactionsProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">
            Recent Transactions
          </h2>
          <Link
            href="/dashboard/transactions"
            className="text-sm text-accent hover:text-accent-hover font-medium transition-colors"
          >
            View all
          </Link>
        </div>
      </CardHeader>
      <CardBody className="p-0">
        <div className="divide-y divide-line sm:hidden">
          {transactions.map((tx) => (
            <div key={tx.id} className="px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">
                    {tx.description}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-ink-muted">
                      {formatDate(tx.transaction_date)}
                    </span>
                    {tx.category && (
                      <Badge variant={categoryBadgeVariant(tx.category)}>
                        {tx.category}
                      </Badge>
                    )}
                  </div>
                </div>
                <span
                  className={`max-w-[45%] shrink-0 text-right text-sm font-semibold tabular-nums font-mono ${
                    tx.transaction_type === 'credit' ? 'text-positive' : 'text-negative'
                  }`}
                >
                  {tx.transaction_type === 'credit' ? '+' : '-'} EGP {formatEGP(tx.amount)}
                </span>
              </div>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line">
                <th className="px-6 py-3 text-left text-xs font-medium text-ink-faint uppercase tracking-wider">
                  Date
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-ink-faint uppercase tracking-wider">
                  Description
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-ink-faint uppercase tracking-wider hidden sm:table-cell">
                  Category
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-ink-faint uppercase tracking-wider">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {transactions.map((tx) => (
                <tr
                  key={tx.id}
                  className="hover:bg-surface-sunken transition-colors"
                >
                  <td className="px-6 py-3.5 whitespace-nowrap text-ink-muted">
                    {formatDate(tx.transaction_date)}
                  </td>
                  <td className="px-6 py-3.5">
                    <span className="text-ink font-medium">
                      {tx.description}
                    </span>
                  </td>
                  <td className="px-6 py-3.5 hidden sm:table-cell">
                    {tx.category && (
                      <Badge variant={categoryBadgeVariant(tx.category)}>
                        {tx.category}
                      </Badge>
                    )}
                  </td>
                  <td className="px-6 py-3.5 text-right whitespace-nowrap">
                    <span
                      className={`font-semibold tabular-nums font-mono ${
                        tx.transaction_type === 'credit' ? 'text-positive' : 'text-negative'
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
      </CardBody>
    </Card>
  );
}
