-- Migration: allow 'loans' and 'prepaid_cards' as sync_jobs.job_type
-- The loans and prepaid-cards split-sync endpoints persist a durable job row
-- with these job_type values; without them the insert violated the CHECK
-- constraint (non-fatal, but the job state couldn't survive a restart).
-- Additive change — existing rows unaffected.

ALTER TABLE public.sync_jobs DROP CONSTRAINT IF EXISTS sync_jobs_job_type_check;

ALTER TABLE public.sync_jobs
  ADD CONSTRAINT sync_jobs_job_type_check
  CHECK (job_type IN (
    'full',
    'accounts',
    'credit_cards',
    'certificates',
    'loans',
    'prepaid_cards'
  ));
