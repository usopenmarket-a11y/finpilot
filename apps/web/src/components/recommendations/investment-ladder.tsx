'use client';

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MarketOpportunities } from '@/components/recommendations/market-opportunities';
import {
  getInvestmentPlan,
  sendInvestmentFeedback,
  updateInvestmentAssumptions,
  type InvestmentAssumptionsUpdate,
  type InvestmentPlan,
  type LadderCard,
  type LadderStep,
  type LadderStepStatus,
  type RecommendationPriority,
} from '@/lib/api-client';

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function num(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : parseFloat(String(value ?? ''));
  return Number.isFinite(n) ? n : 0;
}

function egp(value: string | number | null | undefined): string {
  return `EGP ${new Intl.NumberFormat('en-EG', { maximumFractionDigits: 0 }).format(num(value))}`;
}

function pct(value: string | number | null | undefined, digits = 1): string {
  return `${(num(value) * 100).toFixed(digits)}%`;
}

const STATUS_BADGE: Record<LadderStepStatus, { label: string; variant: 'success' | 'warning' | 'info' | 'default' }> = {
  done: { label: 'Done', variant: 'success' },
  action: { label: 'Action', variant: 'warning' },
  info: { label: 'Info', variant: 'info' },
  locked: { label: 'Locked', variant: 'default' },
};

const PRIORITY_BADGE: Record<RecommendationPriority, 'danger' | 'warning' | 'info' | 'default'> = {
  urgent: 'danger',
  high: 'warning',
  medium: 'info',
  low: 'default',
};

const ASSUMPTION_LABELS: Record<string, string> = {
  card_monthly_rate: 'card interest rate',
  inflation_annual: 'inflation',
  emergency_months: 'buffer months',
};

function assumptionLabel(key: string): string {
  if (key.startsWith('loan_rates.')) return 'loan rate';
  return ASSUMPTION_LABELS[key] ?? key;
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function RecommendationItem({
  card,
  busy,
  onFeedback,
}: {
  card: LadderCard;
  busy: boolean;
  onFeedback: (card: LadderCard, action: 'done' | 'snooze' | 'dismiss') => void;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold text-ink">{card.title}</p>
        <Badge variant={PRIORITY_BADGE[card.priority]}>{card.priority}</Badge>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">{card.why}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        {card.amount_egp != null && (
          <div>
            <dt className="text-ink-faint">Amount</dt>
            <dd className="font-mono font-medium tabular-nums text-ink">{egp(card.amount_egp)}</dd>
          </div>
        )}
        {card.impact_monthly_egp != null && (
          <div>
            <dt className="text-ink-faint">Saves / month</dt>
            <dd className="font-mono font-medium tabular-nums text-positive">
              ≈ {egp(card.impact_monthly_egp)}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-ink-faint">Risk</dt>
          <dd className="text-ink">{card.risk}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">When</dt>
          <dd className="text-ink">{card.horizon}</dd>
        </div>
      </dl>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-faint">
          Confidence: {card.confidence}
          {card.assumptions_used.length > 0 &&
            ` · uses your assumed ${card.assumptions_used.map(assumptionLabel).join(', ')}`}
        </p>
        <div className="flex gap-1">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onFeedback(card, 'done')}>
            Done
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onFeedback(card, 'snooze')}>
            Snooze 7 days
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onFeedback(card, 'dismiss')}>
            Not for me
          </Button>
        </div>
      </div>
    </div>
  );
}

function StepRow({
  step,
  index,
  busyId,
  onFeedback,
}: {
  step: LadderStep;
  index: number;
  busyId: string | null;
  onFeedback: (card: LadderCard, action: 'done' | 'snooze' | 'dismiss') => void;
}) {
  const badge = STATUS_BADGE[step.status];
  return (
    <li className={`rounded-xl border border-line p-4 ${step.status === 'locked' ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-sunken text-xs font-semibold text-ink-muted">
          {index + 1}
        </span>
        <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
      <p className="mt-2 text-sm text-ink-muted">{step.summary}</p>
      {step.cards.length > 0 && (
        <div className="mt-3 space-y-3">
          {step.cards.map((card) => (
            <RecommendationItem key={card.id} card={card} busy={busyId === card.id} onFeedback={onFeedback} />
          ))}
        </div>
      )}
    </li>
  );
}

function AssumptionsEditor({
  plan,
  onSave,
}: {
  plan: InvestmentPlan;
  onSave: (update: InvestmentAssumptionsUpdate) => Promise<void>;
}) {
  const a = plan.assumptions;
  const [cardRate, setCardRate] = useState((num(a.card_monthly_rate) * 100).toFixed(2));
  const [inflation, setInflation] = useState((num(a.inflation_annual) * 100).toFixed(1));
  const [months, setMonths] = useState(String(a.emergency_months));
  const [loanRates, setLoanRates] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      plan.loans.map((l) => [l.id, l.source === 'your rate' && l.rate_annual ? (num(l.rate_annual) * 100).toFixed(2) : '']),
    ),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const update: InvestmentAssumptionsUpdate = {
      card_monthly_rate: num(cardRate) / 100,
      inflation_annual: num(inflation) / 100,
      emergency_months: Math.round(num(months)),
    };
    const rates = Object.fromEntries(
      Object.entries(loanRates)
        .filter(([, v]) => v.trim() !== '')
        .map(([id, v]) => [id, num(v) / 100]),
    );
    if (Object.keys(rates).length > 0) update.loan_rates = rates;
    setSaving(true);
    setError(null);
    try {
      await onSave(update);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  const field = 'w-24 rounded-lg border border-line-strong bg-surface px-2 py-1 text-right text-sm font-mono tabular-nums text-ink';
  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        Your bank does not report these rates, so FinPilot uses these values. Values you have saved
        are marked “yours”.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex items-center justify-between gap-2 text-sm text-ink">
          <span>
            Card interest / month
            {a.user_set.includes('card_monthly_rate') && <span className="ml-1 text-xs text-positive">yours</span>}
          </span>
          <span className="flex items-center gap-1">
            <input className={field} inputMode="decimal" value={cardRate} onChange={(e) => setCardRate(e.target.value)} />%
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm text-ink">
          <span>
            Inflation / year
            {a.user_set.includes('inflation_annual') && <span className="ml-1 text-xs text-positive">yours</span>}
          </span>
          <span className="flex items-center gap-1">
            <input className={field} inputMode="decimal" value={inflation} onChange={(e) => setInflation(e.target.value)} />%
          </span>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm text-ink">
          <span>Safety buffer</span>
          <span className="flex items-center gap-1">
            <input className={field} inputMode="numeric" value={months} onChange={(e) => setMonths(e.target.value)} /> mo
          </span>
        </label>
      </div>
      {plan.loans.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">Loan &amp; overdraft rates (per year)</p>
          {plan.loans.map((loan) => (
            <label key={loan.id} className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink">
              <span className="min-w-0">
                <span dir="auto">{loan.label}</span> <span className="text-ink-faint">{loan.masked}</span>
                <span className="ml-2 text-xs text-ink-faint">
                  {loan.source === 'your rate'
                    ? 'yours'
                    : loan.rate_annual
                      ? `${loan.source} (${pct(loan.rate_annual)})`
                      : 'unknown'}
                </span>
              </span>
              <span className="flex items-center gap-1">
                <input
                  className={field}
                  inputMode="decimal"
                  placeholder="—"
                  value={loanRates[loan.id] ?? ''}
                  onChange={(e) => setLoanRates((prev) => ({ ...prev, [loan.id]: e.target.value }))}
                />
                %
              </span>
            </label>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={() => void save()} loading={saving}>
          Save &amp; recalculate
        </Button>
        {error && <p className="text-sm text-negative">{error}</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function InvestmentLadder() {
  const [plan, setPlan] = useState<InvestmentPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAssumptions, setShowAssumptions] = useState(false);

  const token = useCallback(async () => {
    const { data } = await createClient().auth.getSession();
    const accessToken = data.session?.access_token;
    if (!accessToken) throw new Error('Your session has expired. Please sign in again.');
    return accessToken;
  }, []);

  const load = useCallback(async () => {
    try {
      setPlan(await getInvestmentPlan(await token()));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load your plan');
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const onFeedback = async (card: LadderCard, action: 'done' | 'snooze' | 'dismiss') => {
    setBusyId(card.id);
    try {
      await sendInvestmentFeedback(await token(), card.id, action);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save your choice');
    } finally {
      setBusyId(null);
    }
  };

  const onSaveAssumptions = async (update: InvestmentAssumptionsUpdate) => {
    await updateInvestmentAssumptions(await token(), update);
    await load();
  };

  if (error && !plan) {
    return (
      <Card>
        <CardBody>
          <p className="py-4 text-center text-sm text-ink-muted">{error}</p>
        </CardBody>
      </Card>
    );
  }
  if (!plan) {
    return (
      <Card>
        <CardBody>
          <p className="py-6 text-center text-sm text-ink-muted">Building your money plan…</p>
        </CardBody>
      </Card>
    );
  }

  const s = plan.snapshot;
  const stats = [
    { label: 'Monthly spending', value: egp(s.monthly_spend_egp), note: `avg of ${s.months_measured} month(s)` },
    {
      label: 'Cash',
      value: egp(s.cash_egp),
      note: s.buffer_months != null ? `${num(s.buffer_months).toFixed(1)} months of spending` : '—',
    },
    { label: 'Card statements', value: egp(s.card_statement_due_egp), note: `${egp(s.card_balance_egp)} owed now` },
    { label: 'Loans & overdrafts', value: egp(s.loan_balance_egp), note: `${egp(s.borrowed_debts_egp)} owed to people` },
    {
      label: 'Certificates',
      value: egp(s.certificates_egp),
      note: s.best_certificate_rate ? `best rate ${pct(s.best_certificate_rate)}` : '—',
    },
  ];

  return (
    <>
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Your money plan</h2>
            <p className="mt-1 text-sm text-ink-muted">
              The best next use of your money, in order. Built from your synced accounts
              {plan.data_as_of && ` (latest sync ${new Date(plan.data_as_of).toLocaleDateString()})`}.
            </p>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setShowAssumptions((v) => !v)}>
            {showAssumptions ? 'Hide assumptions' : 'Assumptions'}
          </Button>
        </div>
      </CardHeader>
      <CardBody className="space-y-6">
        {showAssumptions && (
          <div className="rounded-xl border border-line bg-surface-sunken p-4">
            <AssumptionsEditor plan={plan} onSave={onSaveAssumptions} />
          </div>
        )}

        {plan.next_best_action && (
          <div className="rounded-xl border border-accent/30 bg-accent/5 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-accent">Next best action</p>
            <p className="mt-1 text-base font-semibold text-ink">{plan.next_best_action.title}</p>
            {plan.next_best_action.impact_monthly_egp != null && (
              <p className="mt-1 text-sm text-ink-muted">
                Saves about {egp(plan.next_best_action.impact_monthly_egp)} a month.
              </p>
            )}
          </div>
        )}

        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-lg bg-surface-sunken p-3">
              <dt className="text-xs text-ink-faint">{stat.label}</dt>
              <dd className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">{stat.value}</dd>
              <dd className="text-xs text-ink-muted">{stat.note}</dd>
            </div>
          ))}
        </dl>

        {error && <p className="text-sm text-negative">{error}</p>}

        <ol className="space-y-3">
          {plan.steps.map((step, i) => (
            <StepRow key={step.key} step={step} index={i} busyId={busyId} onFeedback={(c, a) => void onFeedback(c, a)} />
          ))}
        </ol>

        <div>
          <h3 className="text-sm font-semibold text-ink">What you hold</h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-faint">
                  <th className="py-2 pr-4 font-medium">Holding</th>
                  <th className="py-2 pr-4 text-right font-medium">Value</th>
                  <th className="py-2 pr-4 text-right font-medium">After inflation</th>
                  <th className="py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {plan.holdings.map((h) => (
                  <tr key={h.key} className="border-t border-line align-top">
                    <td className="py-2 pr-4 text-ink">{h.label}</td>
                    <td className="py-2 pr-4 text-right font-mono tabular-nums text-ink">
                      {h.value_egp != null ? egp(h.value_egp) : '—'}
                    </td>
                    <td
                      className={`py-2 pr-4 text-right font-mono tabular-nums ${
                        h.real_return_annual == null
                          ? 'text-ink-faint'
                          : num(h.real_return_annual) >= 0
                            ? 'text-positive'
                            : 'text-negative'
                      }`}
                    >
                      {h.real_return_annual != null ? `${pct(h.real_return_annual)}/yr` : '—'}
                    </td>
                    <td className="py-2 text-ink-muted" dir="auto">
                      {h.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <p className="text-xs text-ink-faint">
          Guidance from your own data and the assumptions above — not financial advice. FinPilot never
          moves money or trades for you.
        </p>
      </CardBody>
    </Card>
    <MarketOpportunities gateOpen={plan.market_gate_open} />
    </>
  );
}
