/**
 * Typed API client for FinPilot backend.
 *
 * All functions read NEXT_PUBLIC_API_URL at call time so they work in both
 * browser and edge environments.  The caller is responsible for providing
 * the Supabase user id via x-user-id where required.
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  init: RequestInit & { userId?: string } = {},
): Promise<T> {
  const { userId, ...rest } = init;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(userId ? { 'x-user-id': userId } : {}),
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
export async function encryptValue(value: string): Promise<string> {
  const response = await apiFetch<{ token: string }>('/api/v1/utils/encrypt', {
    method: 'POST',
    body: JSON.stringify({ value }),
  });
  return response.token;
}

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

export async function listCredentials(userId: string): Promise<CredentialInfo[]> {
  return apiFetch<CredentialInfo[]>('/api/v1/accounts/credentials', {
    method: 'GET',
    userId,
  });
}

export async function saveCredential(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  encryptedUsername: string,
  encryptedPassword: string,
  label?: string,
): Promise<CredentialInfo> {
  return apiFetch<CredentialInfo>('/api/v1/accounts/credentials', {
    method: 'POST',
    userId,
    body: JSON.stringify({
      bank,
      encrypted_username: encryptedUsername,
      encrypted_password: encryptedPassword,
      ...(label !== undefined ? { label } : {}),
    }),
  });
}

export async function deleteCredential(
  userId: string,
  credentialId: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/accounts/credentials/id/${credentialId}`, {
    method: 'DELETE',
    userId,
  });
}

export async function updateCredential(
  userId: string,
  credentialId: string,
  updates: { encryptedUsername?: string; encryptedPassword?: string; label?: string },
): Promise<CredentialInfo> {
  const body: Record<string, string> = {};
  if (updates.encryptedUsername !== undefined) body.encrypted_username = updates.encryptedUsername;
  if (updates.encryptedPassword !== undefined) body.encrypted_password = updates.encryptedPassword;
  if (updates.label !== undefined) body.label = updates.label;

  return apiFetch<CredentialInfo>(`/api/v1/accounts/credentials/id/${credentialId}`, {
    method: 'PATCH',
    userId,
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Sync — async job pattern
// ---------------------------------------------------------------------------

/**
 * Poll a job until it reaches 'complete' or 'failed' status.
 *
 * Internal helper — not exported. All public sync functions delegate here.
 */
async function _pollSyncJob(
  userId: string,
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
          userId,
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
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}${qs}`,
    { method: 'POST', userId }
  );
  const maxWaitMs = 20 * 60 * 1000; // full scrape (login + CC + certs + 4 accounts + re-login)
  return _pollSyncJob(userId, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE demand-deposit accounts and transactions only (skip CC and certs).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 10 minutes.
 */
export async function syncBankAccounts(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/accounts${qs}`,
    { method: 'POST', userId }
  );
  const maxWaitMs = 10 * 60 * 1000;
  return _pollSyncJob(userId, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE credit card accounts and statement transactions only (skip demand-deposit and certs).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankCreditCards(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/credit-cards${qs}`,
    { method: 'POST', userId }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(userId, jobStart.job_id, maxWaitMs);
}

// ---------------------------------------------------------------------------
// Account management
// ---------------------------------------------------------------------------

/**
 * Hide a bank account by setting is_active=false.
 * The account reappears automatically on the next sync.
 */
export async function hideAccount(userId: string, accountId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/accounts/${accountId}`, {
    method: 'PATCH',
    userId,
  });
}

/**
 * Sync NBE certificate/term-deposit accounts only (skip demand-deposit and CC).
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 4 minutes.
 */
export async function syncBankCertificates(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/certificates${qs}`,
    { method: 'POST', userId }
  );
  const maxWaitMs = 4 * 60 * 1000;
  return _pollSyncJob(userId, jobStart.job_id, maxWaitMs);
}

export type ClearDataScope = 'all' | 'accounts' | 'credit_cards' | 'certificates' | 'debts' | 'installments';

export async function clearData(userId: string, scope: ClearDataScope = 'all'): Promise<void> {
  return apiFetch<void>(`/api/v1/data?scope=${scope}`, { method: 'DELETE', userId });
}
