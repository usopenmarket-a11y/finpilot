'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import {
  listCredentials,
  saveCredential,
  deleteCredential,
  syncBank,
  encryptValue,
  type CredentialInfo,
} from '@/lib/api-client';
import { Card, CardHeader, CardBody } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';

type Bank = 'NBE' | 'CIB' | 'BDC' | 'UB';

const BANK_OPTIONS: { value: string; label: string }[] = [
  { value: 'NBE', label: 'National Bank of Egypt (NBE)' },
  { value: 'CIB', label: 'Commercial International Bank (CIB)' },
  { value: 'BDC', label: 'Banque Du Caire (BDC)' },
  { value: 'UB', label: 'United Bank (UB)' },
];

const BANK_LABELS: Record<Bank, string> = {
  NBE: 'National Bank of Egypt',
  CIB: 'Commercial International Bank',
  BDC: 'Banque Du Caire',
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
  return ['NBE', 'CIB', 'BDC', 'UB'].includes(value);
}

interface SyncState {
  loading: boolean;
  error: string | null;
  lastResult: string | null;
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
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Per-bank sync state keyed by bank code
  const [syncStates, setSyncStates] = useState<Record<string, SyncState>>({});

  // Per-bank remove state
  const [removingBank, setRemovingBank] = useState<string | null>(null);

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

      await saveCredential(userId, selectedBank, encUsername, encPassword);

      // Reset form
      setSelectedBank('');
      setUsername('');
      setPassword('');
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

  const handleRemove = async (bank: string) => {
    if (!userId || !isValidBank(bank)) return;
    setRemovingBank(bank);
    try {
      await deleteCredential(userId, bank);
      setCredentials((prev) => prev.filter((c) => c.bank !== bank));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to remove credentials';
      setListError(message);
    } finally {
      setRemovingBank(null);
    }
  };

  const handleSync = async (bank: string) => {
    if (!userId || !isValidBank(bank)) return;

    setSyncStates((prev) => ({
      ...prev,
      [bank]: { loading: true, error: null, lastResult: null },
    }));

    try {
      // syncBank now handles polling internally and can take 2-4 minutes
      const result = await syncBank(userId, bank);
      setSyncStates((prev) => ({
        ...prev,
        [bank]: {
          loading: false,
          error: null,
          lastResult: `Synced ${result.transactions_scraped} transactions (${result.transactions_saved} new)`,
        },
      }));
      // Refresh list to update last_synced_at
      await fetchCredentials(userId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Sync failed';
      setSyncStates((prev) => ({
        ...prev,
        [bank]: { loading: false, error: message, lastResult: null },
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
            <p className="text-sm text-gray-500 dark:text-gray-400">Loading accounts… (may take up to 30s if server is waking up)</p>
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
                const syncState = syncStates[cred.bank];
                const isSyncing = syncState?.loading ?? false;
                const isRemoving = removingBank === cred.bank;

                return (
                  <li key={cred.bank} className="py-4 first:pt-0 last:pb-0">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                      {/* Bank info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {BANK_LABELS[cred.bank as Bank] ?? cred.bank}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          Last synced: {formatDate(cred.last_synced_at)}
                        </p>
                        {syncState?.error && (
                          <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
                            {syncState.error}
                          </p>
                        )}
                        {syncState?.lastResult && (
                          <p className="text-xs text-green-700 dark:text-green-400 mt-0.5">
                            {syncState.lastResult}
                          </p>
                        )}
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
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={isSyncing}
                          disabled={isSyncing || isRemoving}
                          onClick={() => void handleSync(cred.bank)}
                        >
                          Sync Now
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          loading={isRemoving}
                          disabled={isSyncing || isRemoving}
                          onClick={() => void handleRemove(cred.bank)}
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
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
