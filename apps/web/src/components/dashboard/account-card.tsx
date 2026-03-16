import { type ReactNode } from 'react';
import { Card, CardBody } from '@/components/ui/card';

interface AccountCardProps {
  label: string;
  amount: number;
  currency?: string;
  trend: 'up' | 'down' | 'neutral';
  changePercent: number;
  icon: ReactNode;
}

function formatAmount(amount: number, currency: string): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function TrendArrow({ trend, changePercent }: { trend: 'up' | 'down' | 'neutral'; changePercent: number }) {
  if (trend === 'neutral') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
        — {changePercent.toFixed(1)}%
      </span>
    );
  }

  const isUp = trend === 'up';
  const colorClass = isUp
    ? 'text-green-600 dark:text-green-400'
    : 'text-red-500 dark:text-red-400';

  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${colorClass}`}>
      {isUp ? (
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
        </svg>
      )}
      {changePercent.toFixed(1)}%
    </span>
  );
}

export function AccountCard({
  label,
  amount,
  currency = 'EGP',
  trend,
  changePercent,
  icon,
}: AccountCardProps) {
  return (
    <Card>
      <CardBody className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className="p-2 rounded-lg bg-brand-500/10 text-brand-500">{icon}</div>
          <TrendArrow trend={trend} changePercent={changePercent} />
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">{label}</p>
        <p className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">
          {currency} {formatAmount(amount, currency)}
        </p>
      </CardBody>
    </Card>
  );
}
