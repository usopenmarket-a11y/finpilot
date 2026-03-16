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
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            Recent Transactions
          </h2>
          <Link
            href="/dashboard/transactions"
            className="text-sm text-brand-500 hover:text-green-600 font-medium transition-colors"
          >
            View all
          </Link>
        </div>
      </CardHeader>
      <CardBody className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Date
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Description
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                  Category
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {transactions.map((tx) => (
                <tr
                  key={tx.id}
                  className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-6 py-3.5 whitespace-nowrap text-gray-500 dark:text-gray-400">
                    {formatDate(tx.transaction_date)}
                  </td>
                  <td className="px-6 py-3.5">
                    <span className="text-gray-900 dark:text-gray-100 font-medium">
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
      </CardBody>
    </Card>
  );
}
