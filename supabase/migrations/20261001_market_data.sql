-- Market data for the investment recommendations market layer.
-- Additive only. Rows are shared (not per user): any signed-in user may read
-- them; only the service role (the market worker) writes them.

CREATE TABLE public.market_instruments (
    symbol text PRIMARY KEY,
    name text NOT NULL,
    asset_class text NOT NULL CHECK (asset_class IN ('fx', 'gold', 'stock', 'index', 'crypto')),
    unit text NOT NULL,
    quote_currency text NOT NULL,
    signals_enabled boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 100,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- One close per instrument per day (the latest quote updates today's row).
CREATE TABLE public.market_daily (
    symbol text NOT NULL REFERENCES public.market_instruments(symbol) ON DELETE CASCADE,
    day date NOT NULL,
    close numeric(20, 6) NOT NULL CHECK (close > 0),
    PRIMARY KEY (symbol, day)
);

CREATE TABLE public.market_quotes (
    symbol text PRIMARY KEY REFERENCES public.market_instruments(symbol) ON DELETE CASCADE,
    price numeric(20, 6) NOT NULL CHECK (price > 0),
    as_of timestamptz NOT NULL,
    source text NOT NULL
);

CREATE TABLE public.market_signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol text NOT NULL REFERENCES public.market_instruments(symbol) ON DELETE CASCADE,
    kind text NOT NULL,
    strength text NOT NULL CHECK (strength IN ('strong', 'moderate')),
    title text NOT NULL,
    detail text NOT NULL,
    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_on date NOT NULL,
    expires_on date NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (symbol, kind, created_on)
);
CREATE INDEX market_signals_active_idx ON public.market_signals (expires_on);

CREATE TABLE public.market_worker_status (
    id text PRIMARY KEY,
    last_quotes_at timestamptz,
    last_history_at timestamptz,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.market_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_worker_status ENABLE ROW LEVEL SECURITY;

CREATE POLICY market_instruments_read ON public.market_instruments FOR SELECT TO authenticated USING (true);
CREATE POLICY market_daily_read ON public.market_daily FOR SELECT TO authenticated USING (true);
CREATE POLICY market_quotes_read ON public.market_quotes FOR SELECT TO authenticated USING (true);
CREATE POLICY market_signals_read ON public.market_signals FOR SELECT TO authenticated USING (true);
CREATE POLICY market_worker_status_read ON public.market_worker_status FOR SELECT TO authenticated USING (true);
-- No INSERT/UPDATE/DELETE policies: only the service role writes.
