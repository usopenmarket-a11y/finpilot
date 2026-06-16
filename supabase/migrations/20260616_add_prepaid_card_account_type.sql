-- Migration: allow 'prepaid_card' as a bank_accounts.account_type
-- NBE's dashboard exposes a Prepaid Cards (li.PRE) widget; the scraper now
-- extracts those cards. Additive change — existing rows are unaffected.

-- Drop old constraint
ALTER TABLE bank_accounts DROP CONSTRAINT IF EXISTS bank_accounts_account_type_check;

-- Add new constraint with 'prepaid_card' appended
ALTER TABLE bank_accounts
  ADD CONSTRAINT bank_accounts_account_type_check
  CHECK (account_type IN (
    'savings', 'current', 'payroll',
    'credit', 'credit_card',
    'loan',
    'certificate', 'deposit',
    'prepaid_card'
  ));
