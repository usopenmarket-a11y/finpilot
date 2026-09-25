-- Minimal pre-migration schema contract for isolated PostgreSQL regression
-- tests. This is not a production bootstrap migration.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role BYPASSRLS; END IF;
END $$;
CREATE SCHEMA auth;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
    $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA auth, public TO authenticated, service_role;

CREATE TABLE public.debts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL,
    original_amount numeric(15,2) NOT NULL CHECK (original_amount > 0),
    outstanding_balance numeric(15,2) NOT NULL CHECK (outstanding_balance >= 0),
    status text NOT NULL DEFAULT 'active', updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.debt_payments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    debt_id uuid NOT NULL REFERENCES public.debts(id) ON DELETE CASCADE,
    amount numeric(15,2) NOT NULL CHECK (amount > 0),
    payment_date date NOT NULL, notes text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.bank_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL,
    bank text NOT NULL, label text
);
CREATE TABLE public.bank_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL,
    bank_name text NOT NULL, account_type text NOT NULL,
    credential_label text, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE public.transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL,
    account_id uuid NOT NULL REFERENCES public.bank_accounts(id) ON DELETE CASCADE,
    external_id text NOT NULL, amount numeric(15,2) NOT NULL CHECK (amount > 0),
    currency text NOT NULL DEFAULT 'EGP', transaction_type text NOT NULL,
    description text NOT NULL, category text, sub_category text,
    transaction_date date NOT NULL, value_date date, balance_after numeric(15,2),
    raw_data jsonb, is_categorized boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(account_id, external_id)
);
ALTER TABLE public.debts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debt_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bank_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bank_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_debts ON public.debts TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY own_payments ON public.debt_payments TO authenticated
    USING (EXISTS (SELECT FROM public.debts d WHERE d.id = debt_id AND d.user_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT FROM public.debts d WHERE d.id = debt_id AND d.user_id = auth.uid()));
CREATE POLICY own_accounts ON public.bank_accounts TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY own_credentials ON public.bank_credentials TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY own_transactions ON public.transactions TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated, service_role;
