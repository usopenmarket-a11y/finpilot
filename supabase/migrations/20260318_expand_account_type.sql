-- Migration: expand bank_accounts.account_type allowed values
-- Adds: payroll, credit_card, certificate, deposit
-- Renames: credit → credit_card for existing rows

-- Drop old constraint
ALTER TABLE bank_accounts DROP CONSTRAINT IF EXISTS bank_accounts_account_type_check;

-- Add new constraint with expanded values
ALTER TABLE bank_accounts
  ADD CONSTRAINT bank_accounts_account_type_check
  CHECK (account_type IN (
    'savings', 'current', 'payroll',
    'credit', 'credit_card',
    'loan',
    'certificate', 'deposit'
  ));

-- Update existing rows that used 'credit' to use the more specific 'credit_card'
UPDATE bank_accounts SET account_type = 'credit_card' WHERE account_type = 'credit';
