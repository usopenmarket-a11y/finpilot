/**
 * Typed API client for FinPilot backend.
 *
 * All functions read NEXT_PUBLIC_API_URL at call time so they work in both
 * browser and edge environments.  The caller is responsible for providing a
 * valid Supabase session access token, which is sent as
 * `Authorization: Bearer <accessToken>`. The backend derives the user id
 * from this JWT — callers should obtain it via
 * `(await supabase.auth.getSession()).data.session?.access_token` using
 * either `@/lib/supabase/client` (client components) or
 * `@/lib/supabase/server` (server components).
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'https://finpilot-api-lrfg.onrender.com';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CredentialInfo {
  id: string;
  bank: string;
  label: string | null;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
}

export interface SyncResult {
  bank: string;
  account_number_masked: string;
  transactions_scraped: number;
  transactions_saved: number;
  synced_at: string;
}

export interface SyncJobStartResponse {
  job_id: string;
  status: string;
}

export interface SyncJobStatusResponse {
  job_id: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  result: SyncResult | null;
  error: string | null;
}

export interface UserPreferences {
  fawry_rate?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Thrown when an API call is attempted without a valid Supabase session
 * access token, or when the backend rejects the token with 401 Unauthorized.
 * Callers should treat this as "not authenticated" — typically by
 * redirecting to login.
 */
export class UnauthorizedError extends Error {
  constructor(message = 'No active Supabase session — please sign in again.') {
    super(message);
    this.name = 'UnauthorizedError';
  }
}

async function apiFetch<T>(
  path: string,
  init: RequestInit & { accessToken?: string } = {},
): Promise<T> {
  const { accessToken, ...rest } = init;

  if (!accessToken) {
    throw new UnauthorizedError();
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${accessToken}`,
    ...(rest.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers,
    signal: AbortSignal.timeout(60000), // 60s — Render free tier can take 30s to wake
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore parse errors — use statusText fallback
    }
    if (res.status === 401) {
      throw new UnauthorizedError(detail);
    }
    throw new Error(detail);
  }

  // 204 No Content — return undefined cast as T
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Encrypt helper
// ---------------------------------------------------------------------------

/**
 * Encrypt a plaintext value using the server-side AES-256-GCM key.
 * This keeps the encryption key off the client entirely.
 */
export async function encryptValue(accessToken: string, value: string): Promise<string> {
  const response = await apiFetch<{ token: string }>('/api/v1/utils/encrypt', {
    method: 'POST',
    accessToken,
    body: JSON.stringify({ value }),
  });
  return response.token;
}

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

export async function listCredentials(accessToken: string): Promise<CredentialInfo[]> {
  return apiFetch<CredentialInfo[]>('/api/v1/accounts/credentials', {
    method: 'GET',
    accessToken,
  });
}

export async function saveCredential(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  encryptedUsername: string,
  encryptedPassword: string,
  label?: string,
): Promise<CredentialInfo> {
  return apiFetch<CredentialInfo>('/api/v1/accounts/credentials', {
    method: 'POST',
    accessToken,
    body: JSON.stringify({
      bank,
      encrypted_username: encryptedUsername,
      encrypted_password: encryptedPassword,
      ...(label !== undefined ? { label } : {}),
    }),
  });
}

export async function deleteCredential(
  accessToken: string,
  credentialId: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/accounts/credentials/id/${credentialId}`, {
    method: 'DELETE',
    accessToken,
  });
}

export async function updateCredential(
  accessToken: string,
  credentialId: string,
  updates: { encryptedUsername?: string; encryptedPassword?: string; label?: string },
): Promise<CredentialInfo> {
  const body: Record<string, string> = {};
  if (updates.encryptedUsername !== undefined) body.encrypted_username = updates.encryptedUsername;
  if (updates.encryptedPassword !== undefined) body.encrypted_password = updates.encryptedPassword;
  if (updates.label !== undefined) body.label = updates.label;

  return apiFetch<CredentialInfo>(`/api/v1/accounts/credentials/id/${credentialId}`, {
    method: 'PATCH',
    accessToken,
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// User preferences
// ---------------------------------------------------------------------------

export async function getPreferences(accessToken: string): Promise<UserPreferences> {
  const response = await apiFetch<{ preferences: UserPreferences }>('/api/v1/user/preferences', {
    method: 'GET',
    accessToken,
  });
  return response.preferences;
}

export async function savePreferences(
  accessToken: string,
  preferences: UserPreferences,
): Promise<UserPreferences> {
  const response = await apiFetch<{ preferences: UserPreferences }>('/api/v1/user/preferences', {
    method: 'PATCH',
    accessToken,
    body: JSON.stringify({ preferences }),
  });
  return response.preferences;
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

/**
 * Poll a job until it reaches 'complete' or 'failed' status.
 *
 * Internal helper - not exported. All public sync functions delegate here.
 */
async function _pollSyncJob(
  accessToken: string,
  jobId: string,
  maxWaitMs: number,
): Promise<SyncResult> {
  const pollIntervalMs = 5 * 1000; // 5 seconds
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    let jobStatus: SyncJobStatusResponse;
    try {
      jobStatus = await apiFetch<SyncJobStatusResponse>(
        `/api/v1/accounts/sync/status/${jobId}`,
        {
          method: 'GET',
          accessToken,
        }
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 404 means the backend restarted mid-scrape and lost the in-memory job.
      if (msg.includes('Not Found') || msg.includes('not found')) {
        throw new Error(
          'Sync was interrupted — the server restarted mid-scrape. Please try again.',
        );
      }
      throw err;
    }

    if (jobStatus.status === 'complete') {
      if (!jobStatus.result) {
        throw new Error('Job completed but no result returned');
      }
      return jobStatus.result;
    }

    if (jobStatus.status === 'failed') {
      throw new Error(jobStatus.error ?? 'Sync job failed');
    }

    // Status is 'pending' or 'running' — wait before polling again
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  const minutes = Math.round(maxWaitMs / 60000);
  throw new Error(`Sync job timed out after ${minutes} minutes`);
}

/**
 * Start a bank sync job and poll until completion.
 *
 * The backend sync can take 2-4 minutes due to Cloudflare's 100-second HTTP timeout,
 * so this uses a background job pattern:
 * 1. POST /accounts/sync/{bank} returns immediately with a job_id (HTTP 202)
 * 2. Poll GET /accounts/sync/status/{job_id} every 5 seconds
 * 3. Return result when status is 'complete' or 'failed' (max 20 minutes)
 */
export async function syncBank(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 20 * 60 * 1000; // full scrape (login + CC + certs + 4 accounts + re-login)
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE demand-deposit accounts and transactions only (skip CC and certs).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 15 minutes (heaviest phase).
 */
export async function syncBankAccounts(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/accounts${qs}`,
    { method: 'POST', accessToken }
  );
  // Accounts is the heaviest NBE phase (login + up to 4 demand-deposit
  // accounts, each with transaction pagination, plus session recovery), so it
  // gets the most client-side polling headroom before we give up on the job.
  const maxWaitMs = 15 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE credit card accounts and statement transactions only (skip demand-deposit and certs).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankCreditCards(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/credit-cards${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

// ---------------------------------------------------------------------------
// Account management
// ---------------------------------------------------------------------------

/**
 * Hide a bank account by setting is_active=false.
 * The account reappears automatically on the next sync.
 */
export async function hideAccount(accessToken: string, accountId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/accounts/${accountId}`, {
    method: 'PATCH',
    accessToken,
  });
}

/**
 * Sync NBE certificate/term-deposit accounts only (skip demand-deposit and CC).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 4 minutes.
 */
export async function syncBankCertificates(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/certificates${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 4 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE loan / finance accounts only.
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankLoans(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/loans${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE prepaid card accounts only.
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankPrepaidCards(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/prepaid-cards${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

export type ClearDataScope = 'all' | 'accounts' | 'credit_cards' | 'certificates' | 'debts' | 'installments';

export async function clearData(accessToken: string, scope: ClearDataScope = 'all'): Promise<void> {
  return apiFetch<void>(`/api/v1/data?scope=${scope}`, { method: 'DELETE', accessToken });
}

export async function recategorizeTransactions(accessToken: string): Promise<{ processed: number; updated: number }> {
  return apiFetch<{ processed: number; updated: number }>('/api/v1/analytics/recategorize', {
    method: 'POST',
    accessToken,
  });
}

// ---------------------------------------------------------------------------
// Recommendations — wire-format request types
// ---------------------------------------------------------------------------
//
// These mirror the backend's Pydantic wire models in
// `apps/api/app/routers/recommendations.py` exactly (field names and shapes).
// All `*Request` models use `extra="forbid"`, so any extra field causes a 422.
//
// IMPORTANT — Decimal serialization: backend fields typed as `Decimal`
// serialize to JSON **strings** (Pydantic v2 default), while `float` fields
// serialize as JSON numbers. The response interfaces below reflect this:
// money-like fields (`projected_savings`, `estimated_impact`,
// `estimated_monthly_saving`, totals, balances, rates, payments, etc.) are
// typed as `string` and must be parsed with `Number(...)` before use. Fields
// like `health_score`, `confidence`, `confidence_score`, and `percentage`
// are `float` and arrive as `number`.

export interface CategoryBreakdownInput {
  category: string;
  total: number;
  transaction_count: number;
  percentage: number;
}

export interface SpendingBreakdownInput {
  total_debits: number;
  total_credits: number;
  net: number;
  by_category: CategoryBreakdownInput[];
}

export interface MonthlyPointInput {
  year: number;
  month: number;
  total_debits: number;
  total_credits: number;
  net: number;
  transaction_count: number;
}

export interface TrendReportInput {
  lookback_months: number;
  monthly_points: MonthlyPointInput[];
  avg_monthly_spend: number;
  avg_monthly_income: number;
  spend_trend_direction: 'up' | 'down' | 'flat';
}

export interface DebtItemInput {
  id: string;
  name: string;
  debt_type: 'loan' | 'lent' | 'borrowed';
  outstanding_balance: number;
  interest_rate: number;
  minimum_payment: number;
  currency: string;
}

export interface TransactionSummaryInput {
  description: string;
  amount: number;
  transaction_type: 'debit' | 'credit';
  transaction_date: string;
  category: string | null;
}

export interface MonthlyPlanRequestBody {
  spending: SpendingBreakdownInput;
  trends: TrendReportInput;
  target_month: number;
  target_year: number;
}

export interface ForecastRequestBody {
  trends: TrendReportInput;
  from_date?: string;
}

export interface DebtOptimizerRequestBody {
  debts: DebtItemInput[];
  monthly_budget: number;
}

export interface SavingsRequestBody {
  transactions: TransactionSummaryInput[];
}

// ---------------------------------------------------------------------------
// Recommendations — response types
// ---------------------------------------------------------------------------

export interface ActionItemResponse {
  priority: 'high' | 'medium' | 'low';
  category: 'spending' | 'savings' | 'debt' | 'income';
  title: string;
  description: string;
  /** Decimal on the wire -> JSON string. */
  estimated_impact: string;
  confidence_score: number;
  generated_at: string;
}

export interface MonthlyPlanResponse {
  month: number;
  year: number;
  summary: string;
  action_items: ActionItemResponse[];
  /** Decimal on the wire -> JSON string. */
  projected_savings: string;
  /** Float 0.0-1.0 -> JSON number. */
  health_score: number;
  confidence_score: number;
  generated_at: string;
}

export interface ForecastPointResponse {
  year: number;
  month: number;
  /** Decimal on the wire -> JSON string. */
  projected_income: string;
  /** Decimal on the wire -> JSON string. */
  projected_expenses: string;
  /** Decimal on the wire -> JSON string. */
  projected_net: string;
  confidence: number;
  confidence_score: number;
  generated_at: string;
}

export interface CashFlowForecastResponse {
  forecast_points: ForecastPointResponse[];
  /** Decimal on the wire -> JSON string. */
  avg_projected_monthly_net: string;
  trend_direction: string;
  confidence_score: number;
  generated_at: string;
}

export interface SavingsOpportunityResponse {
  opportunity_type: 'duplicate_charge' | 'recurring_subscription' | 'high_fee' | 'irregular_spike';
  title: string;
  description: string;
  /** Decimal on the wire -> JSON string. */
  estimated_monthly_saving: string;
  transactions: string[];
  confidence_score: number;
  generated_at: string;
}

export interface SavingsReportResponse {
  opportunities: SavingsOpportunityResponse[];
  /** Decimal on the wire -> JSON string. */
  total_estimated_monthly_saving: string;
  analysis_period_days: number;
  confidence_score: number;
  generated_at: string;
}

export interface PayoffStepResponse {
  month: number;
  debt_id: string;
  /** Decimal on the wire -> JSON string. */
  payment: string;
  /** Decimal on the wire -> JSON string. */
  remaining_balance: string;
  /** Decimal on the wire -> JSON string. */
  interest_charged: string;
}

export interface DebtStrategyResponse {
  strategy_name: 'snowball' | 'avalanche';
  total_months: number;
  /** Decimal on the wire -> JSON string. */
  total_interest_paid: string;
  /** Decimal on the wire -> JSON string. */
  total_paid: string;
  monthly_steps: PayoffStepResponse[];
  confidence_score: number;
  generated_at: string;
}

export interface DebtItemResponse {
  id: string;
  name: string;
  debt_type: 'loan' | 'lent' | 'borrowed';
  /** Decimal on the wire -> JSON string. */
  outstanding_balance: string;
  /** Decimal on the wire -> JSON string. */
  interest_rate: string;
  /** Decimal on the wire -> JSON string. */
  minimum_payment: string;
  currency: string;
}

export interface DebtOptimizationReportResponse {
  debts: DebtItemResponse[];
  /** Decimal on the wire -> JSON string. */
  monthly_budget: string;
  snowball: DebtStrategyResponse;
  avalanche: DebtStrategyResponse;
  recommended_strategy: 'snowball' | 'avalanche';
  recommended_reason: string;
  /** Decimal on the wire -> JSON string. */
  interest_savings: string;
  confidence_score: number;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Recommendations — API functions
// ---------------------------------------------------------------------------

export async function getMonthlyPlan(
  accessToken: string,
  body: MonthlyPlanRequestBody,
): Promise<MonthlyPlanResponse> {
  return apiFetch<MonthlyPlanResponse>('/api/v1/recommendations/monthly-plan', {
    method: 'POST',
    accessToken,
    body: JSON.stringify(body),
  });
}

export async function getCashFlowForecast(
  accessToken: string,
  body: ForecastRequestBody,
): Promise<CashFlowForecastResponse> {
  return apiFetch<CashFlowForecastResponse>('/api/v1/recommendations/forecast', {
    method: 'POST',
    accessToken,
    body: JSON.stringify(body),
  });
}

export async function getSavingsReport(
  accessToken: string,
  body: SavingsRequestBody,
): Promise<SavingsReportResponse> {
  return apiFetch<SavingsReportResponse>('/api/v1/recommendations/savings', {
    method: 'POST',
    accessToken,
    body: JSON.stringify(body),
  });
}

export async function getDebtPayoffPlan(
  accessToken: string,
  body: DebtOptimizerRequestBody,
): Promise<DebtOptimizationReportResponse> {
  return apiFetch<DebtOptimizationReportResponse>('/api/v1/recommendations/debt-optimizer', {
    method: 'POST',
    accessToken,
    body: JSON.stringify(body),
  });
}
