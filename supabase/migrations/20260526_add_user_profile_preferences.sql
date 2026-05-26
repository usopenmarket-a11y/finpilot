-- Store per-user application preferences, including the Fawry interest rate
-- used by the credit-card repayment tracker.

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.user_profiles.preferences IS
  'Application preferences keyed by feature, e.g. {"fawry_rate": 0.01}.';
