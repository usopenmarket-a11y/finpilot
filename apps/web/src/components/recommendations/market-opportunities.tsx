'use client';

import { useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getMarketOverview, type MarketInstrument, type MarketOverview } from '@/lib/api-client';

const REFRESH_MS = 5 * 60 * 1000;

function formatPrice(inst: MarketInstrument): string {
  const price = parseFloat(inst.price ?? '');
  if (!Number.isFinite(price)) return '—';
  const digits = price >= 1000 ? 0 : 2;
  return new Intl.NumberFormat('en-EG', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(price);
}

function Change({ value }: { value: number | null }) {
  if (value == null) return <span className="text-ink-faint">—</span>;
  const cls = value > 0 ? 'text-positive' : value < 0 ? 'text-negative' : 'text-ink-muted';
  return (
    <span className={`font-mono tabular-nums ${cls}`}>
      {value > 0 ? '+' : ''}
      {(value * 100).toFixed(1)}%
    </span>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return <span className="text-xs text-ink-faint">—</span>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const w = 80;
  const h = 24;
  const path = points
    .map((p, i) => `${((i / (points.length - 1)) * w).toFixed(1)},${(h - ((p - min) / span) * h).toFixed(1)}`)
    .join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="text-ink-muted" aria-hidden="true">
      <polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function minutesAgo(iso: string | null): string {
  if (!iso) return 'never';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `${Math.round(mins / 60)} h ago`;
}

export function MarketOpportunities({ gateOpen }: { gateOpen: boolean }) {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const { data: session } = await createClient().auth.getSession();
        const token = session.session?.access_token;
        if (!token) throw new Error('Your session has expired. Please sign in again.');
        const overview = await getMarketOverview(token);
        if (!cancelled) {
          setData(overview);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Market data unavailable');
      }
    };
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Market opportunities</h2>
            <p className="mt-1 text-sm text-ink-muted">
              USD, EUR, gold, Egyptian and US stocks, and crypto — checked around the clock.
            </p>
          </div>
          {data && (
            <Badge variant={data.stale ? 'warning' : 'success'}>
              {data.stale ? `Stale · updated ${minutesAgo(data.last_quotes_at)}` : `Updated ${minutesAgo(data.last_quotes_at)}`}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardBody className="space-y-5">
        {error && !data && <p className="py-4 text-center text-sm text-ink-muted">{error}</p>}
        {!data && !error && <p className="py-4 text-center text-sm text-ink-muted">Loading market data…</p>}
        {data && (
          <>
            {!gateOpen && (
              <div className="rounded-lg border border-warning/30 bg-warning-soft p-3 text-sm text-ink">
                Your plan comes first: these are for later. Buying while you carry card or costly-loan
                interest usually costs more than an opportunity can earn.
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-ink">Buy windows flagged now</h3>
              {data.signals.length === 0 ? (
                <p className="mt-2 text-sm text-ink-muted">
                  Nothing is flagged right now. FinPilot only flags a dip when the same setup was
                  usually followed by a higher price in that market’s own history.
                </p>
              ) : (
                <div className="mt-2 space-y-3">
                  {data.signals.map((s) => (
                    <div key={`${s.symbol}-${s.kind}`} className="rounded-lg border border-line p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="text-sm font-semibold text-ink">{s.title}</p>
                        <Badge variant={s.strength === 'strong' ? 'info' : 'default'}>{s.strength}</Badge>
                      </div>
                      <p className="mt-2 text-sm text-ink-muted">{s.detail}</p>
                      <p className="mt-2 text-xs text-ink-faint">
                        Flagged {s.created_on} · expires {s.expires_on} unless it repeats
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-ink-faint">
                    <th className="py-2 pr-4 font-medium">Market</th>
                    <th className="py-2 pr-4 text-right font-medium">Price</th>
                    <th className="py-2 pr-4 text-right font-medium">1 day</th>
                    <th className="py-2 pr-4 text-right font-medium">30 days</th>
                    <th className="py-2 font-medium">30-day trend</th>
                  </tr>
                </thead>
                <tbody>
                  {data.instruments.map((inst) => (
                    <tr key={inst.symbol} className="border-t border-line align-middle">
                      <td className="py-2 pr-4">
                        <p className="text-ink">{inst.name}</p>
                        <p className="text-xs text-ink-faint">
                          {inst.unit}
                          {!inst.signals_enabled && ' · price tracking only'}
                          {inst.signals_enabled && inst.history_days < 120 && ' · not enough history for signals'}
                        </p>
                      </td>
                      <td className="py-2 pr-4 text-right font-mono tabular-nums text-ink">{formatPrice(inst)}</td>
                      <td className="py-2 pr-4 text-right">
                        <Change value={inst.change_1d} />
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <Change value={inst.change_30d} />
                      </td>
                      <td className="py-2">
                        <Sparkline points={inst.sparkline} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-xs text-ink-faint">
              Free data from Yahoo Finance with fallbacks; prices can be delayed. Gold and silver are
              world prices in EGP per gram — shop prices add a premium. Crypto is tracked without buy
              signals because the Central Bank of Egypt prohibits unlicensed crypto trading. Not
              financial advice.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
