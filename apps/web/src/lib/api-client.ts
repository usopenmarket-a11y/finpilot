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
  bank: string;
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
  bank: 'NBE' | 'CIB' | 'BDC' | 'UB',
  encryptedUsername: string,
  encryptedPassword: string,
): Promise<CredentialInfo> {
  return apiFetch<CredentialInfo>('/api/v1/accounts/credentials', {
    method: 'POST',
    userId,
    body: JSON.stringify({
      bank,
      encrypted_username: encryptedUsername,
      encrypted_password: encryptedPassword,
    }),
  });
}

export async function deleteCredential(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'UB',
): Promise<void> {
  return apiFetch<void>(`/api/v1/accounts/credentials/${bank}`, {
    method: 'DELETE',
    userId,
  });
}

// ---------------------------------------------------------------------------
// Sync — async job pattern
// ---------------------------------------------------------------------------

/**
 * Start a bank sync job and poll until completion.
 *
 * The backend sync can take 2-4 minutes due to Cloudflare's 100-second HTTP timeout,
 * so this uses a background job pattern:
 * 1. POST /accounts/sync/{bank} returns immediately with a job_id (HTTP 202)
 * 2. Poll GET /accounts/sync/status/{job_id} every 5 seconds
 * 3. Return result when status is 'complete' or 'failed' (max 5 minutes)
 */
export async function syncBank(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'UB',
): Promise<SyncResult> {
  // Step 1: Start the job
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}`,
    {
      method: 'POST',
      userId,
    }
  );

  const jobId = jobStart.job_id;
  const maxWaitMs = 10 * 60 * 1000; // 10 minutes — 4-account scrape can take 5-8 min
  const pollIntervalMs = 5 * 1000; // 5 seconds
  const startTime = Date.now();

  // Step 2: Poll for completion
  while (Date.now() - startTime < maxWaitMs) {
    const status = await apiFetch<SyncJobStatusResponse>(
      `/api/v1/accounts/sync/status/${jobId}`,
      {
        method: 'GET',
        userId,
      }
    );

    if (status.status === 'complete') {
      if (!status.result) {
        throw new Error('Job completed but no result returned');
      }
      return status.result;
    }

    if (status.status === 'failed') {
      throw new Error(status.error || 'Sync job failed');
    }

    // Status is 'pending' or 'running' — wait before polling again
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  throw new Error('Sync job timed out after 10 minutes');
}
