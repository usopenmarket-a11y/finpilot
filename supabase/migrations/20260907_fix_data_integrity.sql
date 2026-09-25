-- Apply before deploying the matching API/web changes. All mutations below
-- participate in the caller's transaction; failures roll back ledger changes.
BEGIN;

CREATE OR REPLACE FUNCTION public.apply_debt_payment_balance()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    target_id uuid;
    debt public.debts%ROWTYPE;
    deduction numeric;
    new_balance numeric;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.debt_id IS DISTINCT FROM OLD.debt_id THEN
        RAISE EXCEPTION 'A payment cannot be moved to another debt' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        target_id := OLD.debt_id;
        deduction := -OLD.amount;
    ELSE
        target_id := NEW.debt_id;
        IF NEW.amount IS NULL OR NEW.amount <= 0 OR NEW.amount::text IN ('NaN', 'Infinity', '-Infinity') THEN
            RAISE EXCEPTION 'Payment amount must be positive' USING ERRCODE = '23514';
        END IF;
        deduction := NEW.amount;
        IF TG_OP = 'UPDATE' THEN
            deduction := NEW.amount - OLD.amount;
        END IF;
    END IF;

    -- Serialize all payments and original-amount edits for this debt. Read the
    -- latest locked balance, never a balance supplied by a browser.
    SELECT * INTO debt FROM public.debts WHERE id = target_id FOR UPDATE;
    IF NOT FOUND THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD; -- parent deletion cascading into debt_payments
        END IF;
        RAISE EXCEPTION 'Debt not found' USING ERRCODE = '23503';
    END IF;

    new_balance := debt.outstanding_balance - deduction;
    IF new_balance < 0 OR new_balance > debt.original_amount THEN
        RAISE EXCEPTION 'Payment amount exceeds outstanding balance' USING ERRCODE = '23514';
    END IF;
    UPDATE public.debts SET
        outstanding_balance = new_balance,
        status = CASE WHEN new_balance = 0 THEN 'settled'
                      WHEN new_balance < original_amount THEN 'partial'
                      ELSE 'active' END,
        updated_at = now()
    WHERE id = target_id;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER debt_payment_balance
BEFORE INSERT OR UPDATE OR DELETE ON public.debt_payments
FOR EACH ROW EXECUTE FUNCTION public.apply_debt_payment_balance();

CREATE OR REPLACE FUNCTION public.adjust_debt_original_amount()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.original_amount IS DISTINCT FROM OLD.original_amount THEN
        NEW.outstanding_balance := OLD.outstanding_balance + NEW.original_amount - OLD.original_amount;
        IF NEW.outstanding_balance < 0 THEN
            RAISE EXCEPTION 'Original amount cannot be less than payments already recorded'
                USING ERRCODE = '23514';
        END IF;
        NEW.status := CASE WHEN NEW.outstanding_balance = 0 THEN 'settled'
                           WHEN NEW.outstanding_balance < NEW.original_amount THEN 'partial'
                           ELSE 'active' END;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER debt_original_amount_balance
BEFORE UPDATE OF original_amount ON public.debts
FOR EACH ROW EXECUTE FUNCTION public.adjust_debt_original_amount();

ALTER TABLE public.bank_accounts ADD COLUMN credential_id uuid
    REFERENCES public.bank_credentials(id) ON DELETE SET NULL;
CREATE INDEX bank_accounts_credential_id_idx ON public.bank_accounts(credential_id);

-- Only infer ownership where it is unambiguous. Shared/duplicate labels must
-- remain unassigned until the next sync identifies the actual credential.
WITH candidates AS (
    SELECT a.id AS account_id, min(c.id::text)::uuid AS credential_id
    FROM public.bank_accounts a
    JOIN public.bank_credentials c ON c.user_id = a.user_id AND c.bank = a.bank_name
      AND (a.credential_label IS NULL OR a.credential_label = c.label)
    GROUP BY a.id HAVING count(*) = 1
)
UPDATE public.bank_accounts a SET credential_id = c.credential_id
FROM candidates c WHERE a.id = c.account_id;

CREATE OR REPLACE FUNCTION public.hide_deleted_credential_accounts()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE public.bank_accounts SET is_active = false
    WHERE user_id = OLD.user_id AND credential_id = OLD.id;
    RETURN OLD;
END;
$$;

CREATE TRIGGER hide_credential_accounts
BEFORE DELETE ON public.bank_credentials
FOR EACH ROW EXECUTE FUNCTION public.hide_deleted_credential_accounts();

CREATE OR REPLACE FUNCTION public.replace_credit_card_transactions(
    p_account_id uuid, p_user_id uuid, p_transactions jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    saved integer;
BEGIN
    -- Only background/service-role ingestion may replace scraped history.
    PERFORM 1 FROM public.bank_accounts
    WHERE id = p_account_id AND user_id = p_user_id AND account_type = 'credit_card'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Credit card account not found' USING ERRCODE = '23503';
    END IF;
    IF p_transactions IS NULL OR jsonb_typeof(p_transactions) <> 'array'
       OR jsonb_array_length(p_transactions) = 0 THEN
        RAISE EXCEPTION 'A nonempty replacement batch is required' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_populate_recordset(NULL::public.transactions, p_transactions) t
        WHERE t.account_id IS DISTINCT FROM p_account_id OR t.user_id IS DISTINCT FROM p_user_id
    ) THEN
        RAISE EXCEPTION 'Transaction ownership mismatch' USING ERRCODE = '23514';
    END IF;

    -- Empty/missing scraper sections are not evidence of an empty statement.
    -- Replace only sources actually present in this batch, preserving history
    -- when another portal section failed or returned no usable data.
    DELETE FROM public.transactions
    WHERE account_id = p_account_id AND user_id = p_user_id
      AND raw_data->>'source' IN ('nbe_cc_unbilled', 'nbe_cc_unsettled', 'nbe_cc_statement')
      AND raw_data->>'source' IN (
          SELECT value->'raw_data'->>'source' FROM jsonb_array_elements(p_transactions)
      );

    INSERT INTO public.transactions (
        id, user_id, account_id, external_id, amount, currency, transaction_type,
        description, category, sub_category, transaction_date, value_date,
        balance_after, raw_data, is_categorized
    )
    SELECT id, user_id, account_id, external_id, amount, currency, transaction_type,
           description, category, sub_category, transaction_date, value_date,
           balance_after, raw_data, is_categorized
    FROM jsonb_populate_recordset(NULL::public.transactions, p_transactions)
    ON CONFLICT (account_id, external_id) DO UPDATE SET
        amount = EXCLUDED.amount, currency = EXCLUDED.currency,
        transaction_type = EXCLUDED.transaction_type, description = EXCLUDED.description,
        category = EXCLUDED.category, sub_category = EXCLUDED.sub_category,
        transaction_date = EXCLUDED.transaction_date, value_date = EXCLUDED.value_date,
        balance_after = EXCLUDED.balance_after, raw_data = EXCLUDED.raw_data,
        is_categorized = EXCLUDED.is_categorized;
    GET DIAGNOSTICS saved = ROW_COUNT;
    RETURN saved;
END;
$$;

REVOKE ALL ON FUNCTION public.replace_credit_card_transactions(uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_credit_card_transactions(uuid, uuid, jsonb) TO service_role;

COMMIT;
