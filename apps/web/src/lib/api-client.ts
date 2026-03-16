/**
 * Typed API client for FinPilot backend.
 *
 * All functions read NEXT_PUBLIC_API_URL at call time so they work in both
 * browser and edge environments.  The caller is responsible for providing
 * the Supabase user id via x-user-id where required.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

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

  const res = await fetch(`${API_BASE}${path}`, { ...rest, headers });

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
// Sync
// ---------------------------------------------------------------------------

export async function syncBank(
  userId: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'UB',
): Promise<SyncResult> {
  return apiFetch<SyncResult>(`/api/v1/accounts/sync/${bank}`, {
    method: 'POST',
    userId,
  });
}
