-- Migration: add credit card billing detail and certificate metadata columns
--
-- Adds 5 nullable columns to bank_accounts:
--   credit_limit       NUMERIC(15,2) — authorised credit limit (credit_card accounts)
--   billed_amount      NUMERIC(15,2) — current statement billed amount (credit_card accounts)
--   unbilled_amount    NUMERIC(15,2) — pending/unbilled transactions (credit_card accounts)
--   interest_rate      NUMERIC(6,4)  — annual interest rate (certificate/deposit accounts)
--   maturity_date      DATE          — maturity date (certificate/deposit accounts)
--
-- All columns are NULL by default — only populated for the relevant account_type.
-- No RLS changes required: existing bank_accounts RLS policy covers all columns.

ALTER TABLE bank_accounts
  ADD COLUMN IF NOT EXISTS credit_limit     NUMERIC(15,2) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS billed_amount    NUMERIC(15,2) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS unbilled_amount  NUMERIC(15,2) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS interest_rate    NUMERIC(6,4)  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS maturity_date    DATE          DEFAULT NULL;
