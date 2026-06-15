'use client';

import { useState } from 'react';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { ActionItem, SavingsOpportunity } from '@/lib/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

export interface FeedItem {
  id: string;
  source: 'action' | 'savings';
  title: string;
  description: string;
  /** EGP per month impact used for ranking and the value badge. */
  impact: number;
  /** High/medium/low severity used for the accent colour and badge label. */
  severity: 'high' | 'medium' | 'low';
  category: string;
  /** Triggering transaction description strings (savings items only). */
  transactions?: string[];
}

interface ActionFeedProps {
  actionItems: ActionItem[];
  opportunities: SavingsOpportunity[];
}

// ---------------------------------------------------------------------------
// Merge + ranking
// ---------------------------------------------------------------------------

/**
 * Map a savings opportunity's estimated saving to a high/medium/low severity
 * so it can sit alongside action items (which already carry a priority) in a
 * single ranked feed. Thresholds are intentionally coarse — this only drives
 * the accent colour, not the sort order (impact desc handles that).
 */
function savingsSeverity(estimatedMonthlySaving: number): 'high' | 'medium' | 'low' {
  if (estimatedMonthlySaving >= 300) return 'high';
  if (estimatedMonthlySaving >= 100) return 'medium';
  return 'low';
}

function opportunityTypeLabel(opportunityType: string): string {
  switch (opportunityType) {
    case 'duplicate_charge':
      return 'Duplicate Charge';
    case 'recurring_subscription':
      return 'Subscription';
    case 'high_fee':
      return 'Fee';
    case 'irregular_spike':
      return 'Spending Spike';
    default:
      return opportunityType;
  }
}

/**
 * Merge MonthlyPlan.action_items and SavingsReport.opportunities into a
 * single feed ranked by EGP/mo impact (estimated_impact /
 * estimated_monthly_saving), highest first.
 */
export function mergeFeedItems(
  actionItems: ActionItem[],
  opportunities: SavingsOpportunity[],
): FeedItem[] {
  const fromActions: FeedItem[] = actionItems.map((item, idx) => ({
    id: `action-${idx}-${item.title}`,
    source: 'action',
    title: item.title,
    description: item.description,
    impact: item.estimated_impact,
    severity: item.priority,
    category: item.category,
  }));

  const fromSavings: FeedItem[] = opportunities.map((opp, idx) => ({
    id: `savings-${idx}-${opp.title}`,
    source: 'savings',
    title: opp.title,
    description: opp.description,
    impact: opp.estimated_monthly_saving,
    severity: savingsSeverity(opp.estimated_monthly_saving),
    category: opportunityTypeLabel(opp.opportunity_type),
    transactions: opp.transactions,
  }));

  return [...fromActions, ...fromSavings].sort((a, b) => b.impact - a.impact);
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

function severityVariant(severity: FeedItem['severity']): BadgeVariant {
  switch (severity) {
    case 'high':
      return 'danger';
    case 'medium':
      return 'warning';
    case 'low':
      return 'info';
  }
}

const SEVERITY_ACCENT: Record<FeedItem['severity'], string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-500',
  low: 'bg-blue-500',
};

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.round(amount));
}

// ---------------------------------------------------------------------------
// Chevron icon (rotates when expanded)
// ---------------------------------------------------------------------------

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-4 w-4 shrink-0 text-gray-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function FeedRow({ item }: { item: FeedItem }) {
  const [open, setOpen] = useState(false);
  const panelId = `feed-item-${item.id}-details`;

  return (
    <div className="flex gap-3 border-b border-gray-100 py-3 last:border-0 dark:border-gray-800">
      <span
        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${SEVERITY_ACCENT[item.severity]}`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
          aria-controls={panelId}
          className="flex w-full items-start justify-between gap-3 rounded-md text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-gray-900 dark:text-white">{item.title}</p>
              <Badge variant={severityVariant(item.severity)}>
                {item.severity.charAt(0).toUpperCase() + item.severity.slice(1)}
              </Badge>
              <Badge variant="default">{item.category}</Badge>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {item.impact > 0 && (
              <span className="whitespace-nowrap rounded-full bg-brand-500/10 px-2.5 py-0.5 text-xs font-semibold text-brand-500">
                EGP {formatEGP(item.impact)}/mo
              </span>
            )}
            <ChevronIcon open={open} />
          </div>
        </button>

        {open && (
          <div id={panelId} className="mt-2 space-y-2 pe-1 ps-1">
            <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
              {item.description}
            </p>
            {item.transactions && item.transactions.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                  Triggering transactions
                </p>
                <ul className="mt-1 space-y-0.5">
                  {item.transactions.map((tx, idx) => (
                    <li
                      key={`${item.id}-tx-${idx}`}
                      className="truncate text-xs text-gray-500 dark:text-gray-400"
                    >
                      &bull; {tx}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export function ActionFeed({ actionItems, opportunities }: ActionFeedProps) {
  const items = mergeFeedItems(actionItems, opportunities);

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          Prioritised Action Feed
        </h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          What to do first, ranked by estimated monthly impact
        </p>
      </CardHeader>
      <CardBody>
        {items.length > 0 ? (
          <div>
            {items.map((item) => (
              <FeedRow key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-gray-500 dark:text-gray-400">
            No action items right now — your finances look on track.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
