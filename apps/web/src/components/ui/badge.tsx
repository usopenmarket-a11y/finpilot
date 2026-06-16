import { type ReactNode } from 'react';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-surface-sunken text-ink-muted ring-1 ring-inset ring-line',
  success: 'bg-positive-soft text-positive ring-1 ring-inset ring-positive/20',
  warning: 'bg-warning-soft text-warning ring-1 ring-inset ring-warning/20',
  danger: 'bg-negative-soft text-negative ring-1 ring-inset ring-negative/20',
  info: 'bg-info-soft text-info ring-1 ring-inset ring-info/20',
};

export function Badge({ variant = 'default', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium uppercase tracking-wide ${variantClasses[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
