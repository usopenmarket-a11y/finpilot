'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import {
  listCredentials,
  saveCredential,
  deleteCredential,
  syncBank,
  syncBankAccounts,
  syncBankCreditCards,
  syncBankCertificates,
  encryptValue,
  type CredentialInfo,
} from '@/lib/api-client';
import { Card, CardHeader, CardBody } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';

type Bank = 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB';

const BANK_OPTIONS: { value: string; label: string }[] = [
  { value: 'NBE', label: 'National Bank of Egypt (NBE)' },
  { value: 'CIB', label: 'Commercial International Bank (CIB)' },
  { value: 'BDC', label: 'Banque Du Caire — ibanking (BDC)' },
  { value: 'BDC_RETAIL', label: 'Banque Du Caire — Retail (BDC Retail)' },
  { value: 'UB', label: 'United Bank (UB)' },
];

const BANK_LABELS: Record<Bank, string> = {
  NBE: 'National Bank of Egypt',
  CIB: 'Commercial International Bank',
  BDC: 'Banque Du Caire (ibanking)',
  BDC_RETAIL: 'Banque Du Caire (Retail)',
  UB: 'United Bank',
};

function formatDate(iso: string | null): string {
  if (!iso) return 'Never';
  return new Intl.DateTimeFormat('en-EG', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

function isValidBank(value: string): value is Bank {
  return ['NBE', 'CIB', 'BDC', 'BDC_RETAIL', 'UB'].includes(value);
}

interface SyncState {
  loading: boolean;
  error: string | null;
  lastResult: string | null;
  startedAt: number | null;
}

export function BankAccountsSection() {
  const [userId, setUserId] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<CredentialInfo[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // Add-form state
  const [selectedBank, setSelectedBank] = useState<string>('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [label, setLabel] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Per-credential sync state keyed by credential id (or `${credId}_accounts` etc for NBE)
  const [syncStates, setSyncStates] = useState<Record<string, SyncState>>({});

  // Elapsed seconds counter — increments every second for any key currently loading
  const [elapsedSeconds, setElapsedSeconds] = useState<Record<string, number>>({});

  useEffect(() => {
    const anyLoading = Object.values(syncStates).some((s) => s.loading);
    if (!anyLoading) return;

    const interval = setInterval(() => {
      setElapsedSeconds(() => {
        const now = Date.now();
        const next: Record<string, number> = {};
        for (const [key, state] of Object.entries(syncStates)) {
          if (state.loading && state.startedAt !== null) {
            next[key] = Math.floor((now - state.startedAt) / 1000);
          }
        }
        return next;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [syncStates]);

  // Per-credential remove state keyed by credential id
  const [removingId, setRemovingId] = useState<string | null>(null);

  // Fetch user id on mount
  useEffect(() => {
    const supabase = createClient();
    void supabase.auth.getUser().then(({ data }) => {
      if (data.user) setUserId(data.user.id);
    });
  }, []);

  const fetchCredentials = useCallback(async (uid: string) => {
    setLoadingList(true);
    setListError(null);
    try {
      const list = await listCredentials(uid);
      setCredentials(list);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load bank accounts';
      setListError(message);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    if (userId) void fetchCredentials(userId);
  }, [userId, fetchCredentials]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId || !isValidBank(selectedBank)) return;

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      // Encrypt credentials server-side so the key never touches the browser
      const [encUsername, encPassword] = await Promise.all([
        encryptValue(username),
        encryptValue(password),
      ]);

      await saveCredential(
        userId,
        selectedBank,
        encUsername,
        encPassword,
        label.trim() || undefined,
      );

      // Reset form
      setSelectedBank('');
      setUsername('');
      setPassword('');
      setLabel('');
      setSaveSuccess(true);

      // Refresh list
      await fetchCredentials(userId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save credentials';
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (cred: CredentialInfo) => {
    if (!userId) return;
    setRemovingId(cred.id);
    try {
      await deleteCredential(userId, cred.id);
      setCredentials((prev) => prev.filter((c) => c.id !== cred.id));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to remove credentials';
      setListError(message);
    } finally {
      setRemovingId(null);
    }
  };

  const handleSync = async (cred: CredentialInfo) => {
    if (!userId || !isValidBank(cred.bank)) return;
    const key = cred.id;

    setSyncStates((prev) => ({
      ...prev,
      [key]: { loading: true, error: null, lastResult: null, startedAt: Date.now() },
    }));

    try {
      const result = await syncBank(userId, cred.bank as Bank, cred.id);
      setSyncStates((prev) => ({
        ...prev,
        [key]: {
          loading: false,
          error: null,
          lastResult: `Synced ${result.transactions_scraped} transactions (${result.transactions_saved} new)`,
          startedAt: null,
        },
      }));
      // Refresh list to update last_synced_at
      await fetchCredentials(userId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Sync failed';
      setSyncStates((prev) => ({
        ...prev,
        [key]: { loading: false, error: message, lastResult: null, startedAt: null },
      }));
    }
  };

  /**
   * Trigger a focused NBE sync domain (accounts | cc | certs).
   * Uses composite key `${credId}_${domain}` in syncStates so each button
   * tracks its own loading/error/result independently.
   */
  const handleSyncDomain = async (
    cred: CredentialInfo,
    domain: 'accounts' | 'cc' | 'certs',
  ) => {
    if (!userId || !isValidBank(cred.bank)) return;
    const key = `${cred.id}_${domain}`;

    setSyncStates((prev) => ({
      ...prev,
      [key]: { loading: true, error: null, lastResult: null, startedAt: Date.now() },
    }));

    try {
      let result;
      if (domain === 'accounts') {
        result = await syncBankAccounts(userId, cred.bank as Bank, cred.id);
      } else if (domain === 'cc') {
        result = await syncBankCreditCards(userId, cred.bank as Bank, cred.id);
      } else {
        result = await syncBankCertificates(userId, cred.bank as Bank, cred.id);
      }

      setSyncStates((prev) => ({
        ...prev,
        [key]: {
          loading: false,
          error: null,
          lastResult: `Synced ${result.transactions_scraped} transactions (${result.transactions_saved} new)`,
          startedAt: null,
        },
      }));
      await fetchCredentials(userId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Sync failed';
      setSyncStates((prev) => ({
        ...prev,
        [key]: { loading: false, error: message, lastResult: null, startedAt: null },
      }));
    }
  };

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          Connected Bank Accounts
        </h2>
      </CardHeader>
      <CardBody className="space-y-6">
        {/* Existing credentials list */}
        <div>
          {loadingList && (
            <p className="text-sm text-gray-500 dark:text-gray-400">Loading accounts... (may take up to 30s if server is waking up)</p>
          )}
          {listError && (
            <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
              {listError}
            </p>
          )}
          {!loadingList && credentials.length === 0 && !listError && (
            <div className="flex flex-col items-center py-6 gap-2 text-center">
              <div className="p-3 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-400">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"
                  />
                </svg>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs">
                No bank accounts connected yet. Use the form below to add one.
              </p>
            </div>
          )}

          {credentials.length > 0 && (
            <ul className="divide-y divide-gray-200 dark:divide-gray-800">
              {credentials.map((cred) => {
                const syncState = syncStates[cred.id];
                const isSyncing = syncState?.loading ?? false;
                const isRemoving = removingId === cred.id;

                // For NBE, track each domain independently via composite keys.
                const isNBE = cred.bank === 'NBE';
                const accountsState = syncStates[`${cred.id}_accounts`];
                const ccState = syncStates[`${cred.id}_cc`];
                const certsState = syncStates[`${cred.id}_certs`];
                // Any focused sync running counts as "syncing" for Remove disabled state.
                const isAnySyncing =
                  isSyncing ||
                  (accountsState?.loading ?? false) ||
                  (ccState?.loading ?? false) ||
                  (certsState?.loading ?? false);

                // Collect inline feedback messages across all active domains.
                const domainMessages: { key: string; text: string; isError: boolean }[] = [];
                if (isNBE) {
                  for (const [domainKey, domainLabel] of [
                    [`${cred.id}_accounts`, 'Accounts'],
                    [`${cred.id}_cc`, 'CC'],
                    [`${cred.id}_certs`, 'Certs'],
                  ] as [string, string][]) {
                    const ds = syncStates[domainKey];
                    if (ds?.error) {
                      domainMessages.push({ key: domainKey, text: `${domainLabel}: ${ds.error}`, isError: true });
                    } else if (ds?.lastResult) {
                      domainMessages.push({ key: domainKey, text: `${domainLabel}: ${ds.lastResult}`, isError: false });
                    }
                  }
                }

                // Determine which keys are currently syncing for this credential
                // so we can pick the largest elapsed time to display.
                const activeSyncKeys: string[] = isNBE
                  ? [`${cred.id}_accounts`, `${cred.id}_cc`, `${cred.id}_certs`].filter(
                      (k) => syncStates[k]?.loading,
                    )
                  : isSyncing
                  ? [cred.id]
                  : [];
                const maxElapsed =
                  activeSyncKeys.length > 0
                    ? Math.max(...activeSyncKeys.map((k) => elapsedSeconds[k] ?? 0))
                    : 0;

                return (
                  <li key={cred.id} className="py-4 first:pt-0 last:pb-0">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                      {/* Bank info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {cred.label ?? (BANK_LABELS[cred.bank as Bank] ?? cred.bank)}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          {BANK_LABELS[cred.bank as Bank] ?? cred.bank} &middot; Last synced: {formatDate(cred.last_synced_at)}
                        </p>
                        {/* Non-NBE single sync feedback */}
                        {!isNBE && syncState?.error && (
                          <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
                            {syncState.error}
                          </p>
                        )}
                        {!isNBE && syncState?.lastResult && (
                          <p className="text-xs text-green-700 dark:text-green-400 mt-0.5">
                            {syncState.lastResult}
                          </p>
                        )}
                        {/* NBE domain-specific feedback */}
                        {isNBE && domainMessages.map((msg) => (
                          <p
                            key={msg.key}
                            className={`text-xs mt-0.5 ${
                              msg.isError
                                ? 'text-red-600 dark:text-red-400'
                                : 'text-green-700 dark:text-green-400'
                            }`}
                          >
                            {msg.text}
                          </p>
                        ))}
                      </div>

                      {/* Status badge */}
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          cred.is_active
                            ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                            : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                        }`}
                      >
                        {cred.is_active ? 'Active' : 'Inactive'}
                      </span>

                      {/* Actions */}
                      <div className="flex items-center gap-2 shrink-0">
                        {isNBE ? (
                          <>
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={accountsState?.loading ?? false}
                              disabled={isAnySyncing || isRemoving}
                              onClick={() => void handleSyncDomain(cred, 'accounts')}
                            >
                              Accounts
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={ccState?.loading ?? false}
                              disabled={isAnySyncing || isRemoving}
                              onClick={() => void handleSyncDomain(cred, 'cc')}
                            >
                              CC
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={certsState?.loading ?? false}
                              disabled={isAnySyncing || isRemoving}
                              onClick={() => void handleSyncDomain(cred, 'certs')}
                            >
                              Certs
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            loading={isSyncing}
                            disabled={isSyncing || isRemoving}
                            onClick={() => void handleSync(cred)}
                          >
                            Sync Now
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="danger"
                          loading={isRemoving}
                          disabled={isAnySyncing || isRemoving}
                          onClick={() => void handleRemove(cred)}
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
                    {activeSyncKeys.length > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                        Syncing... {maxElapsed}s — this can take 2-4 minutes
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Divider */}
        <div className="border-t border-gray-200 dark:border-gray-800" />

        {/* Add new bank form */}
        <div>
          <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-4">
            Add Bank Account
          </h3>
          <form onSubmit={(e) => void handleSave(e)} className="flex flex-col gap-4">
            <Select
              label="Bank"
              options={BANK_OPTIONS}
              placeholder="Select a bank"
              value={selectedBank}
              onChange={(e) => setSelectedBank(e.target.value)}
              required
            />
            <Input
              label="Label / Nickname (optional)"
              placeholder="e.g. Personal NBE, Business CIB"
              autoComplete="off"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <Input
              label="Username / Customer ID"
              placeholder="Your bank portal username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
            <Input
              label="Password"
              type="password"
              placeholder="Your bank portal password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />

            {saveError && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                {saveError}
              </p>
            )}
            {saveSuccess && (
              <p className="text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                Bank account saved successfully. Your credentials are encrypted and stored securely.
              </p>
            )}

            <p className="text-xs text-gray-500 dark:text-gray-400">
              Credentials are encrypted server-side using AES-256-GCM before storage. They are never
              stored in plaintext and only used to fetch your transaction data.
            </p>

            <div className="flex justify-end">
              <Button
                type="submit"
                loading={saving}
                disabled={!selectedBank || !username || !password}
              >
                Save Bank Account
              </Button>
            </div>
          </form>
        </div>
      </CardBody>
    </Card>
  );
}
