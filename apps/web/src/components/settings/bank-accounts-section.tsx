'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';
import {
  listCredentials,
  saveCredential,
  deleteCredential,
  updateCredential,
  syncBank,
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
  { value: 'BDC', label: 'Banque Du Caire - ibanking (BDC)' },
  { value: 'BDC_RETAIL', label: 'Banque Du Caire - Retail (BDC Retail)' },
  { value: 'UB', label: 'United Bank (UB)' },
];

const BANK_LABELS: Record<Bank, string> = {
  NBE: 'National Bank of Egypt',
  CIB: 'Commercial International Bank',
  BDC: 'Banque Du Caire (ibanking)',
  BDC_RETAIL: 'Banque Du Caire (Retail)',
  UB: 'United Bank',
};

type SyncDomain = 'accounts' | 'cards' | 'certificates';

interface BankAccountSyncRow {
  bank_name: string;
  account_type: string;
  credential_label: string | null;
  last_synced_at: string | null;
}

interface DomainSummary {
  count: number;
  lastSyncedAt: string | null;
}

type SyncSummary = Record<SyncDomain, DomainSummary>;

const SYNC_DOMAINS: { key: SyncDomain; label: string; completeClass: string }[] = [
  { key: 'accounts', label: 'Accounts', completeClass: 'bg-sky-500 dark:bg-sky-400' },
  { key: 'cards', label: 'Cards', completeClass: 'bg-emerald-500 dark:bg-emerald-400' },
  { key: 'certificates', label: 'Certificates', completeClass: 'bg-amber-500 dark:bg-amber-400' },
];

const EMPTY_SYNC_SUMMARY: SyncSummary = {
  accounts: { count: 0, lastSyncedAt: null },
  cards: { count: 0, lastSyncedAt: null },
  certificates: { count: 0, lastSyncedAt: null },
};

const CERTIFICATE_TYPES = new Set(['certificate', 'deposit', 'term_deposit']);
const DEMAND_ACCOUNT_TYPES = new Set(['savings', 'current', 'payroll']);

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

function cloneEmptySyncSummary(): SyncSummary {
  return {
    accounts: { ...EMPTY_SYNC_SUMMARY.accounts },
    cards: { ...EMPTY_SYNC_SUMMARY.cards },
    certificates: { ...EMPTY_SYNC_SUMMARY.certificates },
  };
}

function newerDate(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

function classifySyncDomain(accountType: string): SyncDomain | null {
  if (accountType === 'credit_card') return 'cards';
  if (CERTIFICATE_TYPES.has(accountType)) return 'certificates';
  if (DEMAND_ACCOUNT_TYPES.has(accountType)) return 'accounts';
  return null;
}

function bankAliases(bank: string): Set<string> {
  const aliases = new Set<string>([bank]);
  if (isValidBank(bank)) aliases.add(BANK_LABELS[bank]);
  return aliases;
}

function rowBelongsToCredential(row: BankAccountSyncRow, cred: CredentialInfo): boolean {
  if (!bankAliases(cred.bank).has(row.bank_name)) return false;
  if (!row.credential_label || !cred.label) return true;
  return row.credential_label === cred.label;
}

function buildSyncSummary(rows: BankAccountSyncRow[], cred?: CredentialInfo): SyncSummary {
  const summary = cloneEmptySyncSummary();

  for (const row of rows) {
    if (cred && !rowBelongsToCredential(row, cred)) continue;
    const domain = classifySyncDomain(row.account_type);
    if (!domain) continue;

    summary[domain].count += 1;
    summary[domain].lastSyncedAt = newerDate(summary[domain].lastSyncedAt, row.last_synced_at);
  }

  return summary;
}

function getDomainCountLabel(count: number): string {
  if (count === 0) return 'Not synced';
  if (count === 1) return '1 item';
  return `${count} items`;
}

function getDomainSyncTimeLabel(iso: string | null): string {
  return iso ? `Last synced: ${formatDate(iso)}` : 'No sync time';
}

function SyncCoverageBar({
  summary,
  syncingDomains,
}: {
  summary: SyncSummary;
  syncingDomains: Set<SyncDomain>;
}) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-1 h-2.5 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
        {SYNC_DOMAINS.map((domain) => {
          const domainSummary = summary[domain.key];
          const isSynced = domainSummary.count > 0;
          const isSyncing = syncingDomains.has(domain.key);
          const syncTimeLabel = getDomainSyncTimeLabel(domainSummary.lastSyncedAt);
          return (
            <div
              key={domain.key}
              className={`h-full transition-colors ${
                isSynced ? domain.completeClass : 'bg-gray-200 dark:bg-gray-700'
              } ${isSyncing ? 'sync-bar-animated' : ''}`}
              title={`${domain.label}: ${getDomainCountLabel(domainSummary.count)} - ${syncTimeLabel}`}
            />
          );
        })}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {SYNC_DOMAINS.map((domain) => {
          const domainSummary = summary[domain.key];
          const isSynced = domainSummary.count > 0;
          const syncTimeLabel = getDomainSyncTimeLabel(domainSummary.lastSyncedAt);
          return (
            <div key={domain.key} className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${
                    isSynced ? domain.completeClass : 'bg-gray-300 dark:bg-gray-600'
                  }`}
                />
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                  {domain.label}
                </span>
              </div>
              <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                {getDomainCountLabel(domainSummary.count)}
              </p>
              <p
                className="text-[11px] text-gray-500 dark:text-gray-400 truncate"
                title={syncTimeLabel}
              >
                {syncTimeLabel}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface SyncState {
  loading: boolean;
  error: string | null;
  lastResult: string | null;
  startedAt: number | null;
}

export function BankAccountsSection() {
  const [userId, setUserId] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<CredentialInfo[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [syncedAccounts, setSyncedAccounts] = useState<BankAccountSyncRow[]>([]);
  const [syncInventoryError, setSyncInventoryError] = useState<string | null>(null);

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

  // Elapsed seconds counter - increments every second for any key currently loading
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

  // Inline edit form state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editUsername, setEditUsername] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [editLabel, setEditLabel] = useState('');
  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  // Fetch user id and session access token on mount
  useEffect(() => {
    const supabase = createClient();
    void supabase.auth.getSession().then(({ data }) => {
      if (data.session) {
        setUserId(data.session.user.id);
        setAccessToken(data.session.access_token);
      }
    });
  }, []);

  const fetchCredentials = useCallback(async (token: string) => {
    setLoadingList(true);
    setListError(null);
    try {
      const list = await listCredentials(token);
      setCredentials(list);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load bank accounts';
      setListError(message);
    } finally {
      setLoadingList(false);
    }
  }, []);

  const fetchSyncedAccounts = useCallback(async (uid: string) => {
    setSyncInventoryError(null);
    try {
      const supabase = createClient();
      const { data, error } = await supabase
        .from('bank_accounts')
        .select('bank_name, account_type, credential_label, last_synced_at')
        .eq('user_id', uid)
        .eq('is_active', true);

      if (error) {
        const fallback = await supabase
          .from('bank_accounts')
          .select('bank_name, account_type, last_synced_at')
          .eq('user_id', uid)
          .eq('is_active', true);

        if (fallback.error) throw error;
        setSyncedAccounts(
          ((fallback.data ?? []) as Omit<BankAccountSyncRow, 'credential_label'>[]).map((row) => ({
            ...row,
            credential_label: null,
          })),
        );
        return;
      }

      setSyncedAccounts((data ?? []) as BankAccountSyncRow[]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load sync coverage';
      setSyncInventoryError(message);
    }
  }, []);

  useEffect(() => {
    if (userId && accessToken) {
      void fetchCredentials(accessToken);
      void fetchSyncedAccounts(userId);
    }
  }, [userId, accessToken, fetchCredentials, fetchSyncedAccounts]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId || !accessToken || !isValidBank(selectedBank)) return;

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      // Encrypt credentials server-side so the key never touches the browser
      const [encUsername, encPassword] = await Promise.all([
        encryptValue(accessToken, username),
        encryptValue(accessToken, password),
      ]);

      await saveCredential(
        accessToken,
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
      await Promise.all([fetchCredentials(accessToken), fetchSyncedAccounts(userId)]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save credentials';
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (cred: CredentialInfo) => {
    if (!userId || !accessToken) return;
    setRemovingId(cred.id);
    try {
      await deleteCredential(accessToken, cred.id);
      setCredentials((prev) => prev.filter((c) => c.id !== cred.id));
      await fetchSyncedAccounts(userId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to remove credentials';
      setListError(message);
    } finally {
      setRemovingId(null);
    }
  };

  const handleUpdate = async (cred: CredentialInfo) => {
    if (!userId || !accessToken) return;
    setUpdating(true);
    setUpdateError(null);
    try {
      const updates: { encryptedUsername?: string; encryptedPassword?: string; label?: string } = {};
      if (editUsername.trim()) {
        updates.encryptedUsername = await encryptValue(accessToken, editUsername);
      }
      if (editPassword.trim()) {
        updates.encryptedPassword = await encryptValue(accessToken, editPassword);
      }
      if (editLabel.trim() !== cred.label) {
        updates.label = editLabel.trim();
      }
      if (Object.keys(updates).length === 0) {
        setUpdateError('Enter a new username, password, or label to update');
        return;
      }
      await updateCredential(accessToken, cred.id, updates);
      setEditingId(null);
      setEditUsername('');
      setEditPassword('');
      setEditLabel('');
      await Promise.all([fetchCredentials(accessToken), fetchSyncedAccounts(userId)]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update credentials';
      setUpdateError(message);
    } finally {
      setUpdating(false);
    }
  };

  const handleSync = async (cred: CredentialInfo) => {
    if (!userId || !accessToken || !isValidBank(cred.bank)) return;
    const key = cred.id;

    setSyncStates((prev) => ({
      ...prev,
      [key]: { loading: true, error: null, lastResult: null, startedAt: Date.now() },
    }));

    try {
      const result = await syncBank(accessToken, cred.bank as Bank, cred.id);
      setSyncStates((prev) => ({
        ...prev,
        [key]: {
          loading: false,
          error: null,
          lastResult: `Synced ${result.transactions_scraped} transactions (${result.transactions_saved} new)`,
          startedAt: null,
        },
      }));
      // Refresh list to update last_synced_at and synced-domain coverage.
      await Promise.all([fetchCredentials(accessToken), fetchSyncedAccounts(userId)]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Sync failed';
      setSyncStates((prev) => ({
        ...prev,
        [key]: { loading: false, error: message, lastResult: null, startedAt: null },
      }));
    }
  };

  const globalSummary = buildSyncSummary(syncedAccounts);
  const globalSyncingDomains = new Set<SyncDomain>();
  for (const state of Object.values(syncStates)) {
    if (!state.loading) continue;
    SYNC_DOMAINS.forEach((domain) => globalSyncingDomains.add(domain.key));
  }

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
          {credentials.length > 0 && (
            <div className="mb-4 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 p-3">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 mb-3">
                <p className="text-xs font-semibold text-gray-700 dark:text-gray-200">
                  Sync Coverage
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {syncedAccounts.length} synced item{syncedAccounts.length === 1 ? '' : 's'} found
                </p>
              </div>
              <SyncCoverageBar summary={globalSummary} syncingDomains={globalSyncingDomains} />
              {syncInventoryError && (
                <p className="text-xs text-amber-700 dark:text-amber-300 mt-3">
                  Sync coverage is unavailable: {syncInventoryError}
                </p>
              )}
            </div>
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

                // Any sync running for this credential disables Remove/Edit.
                const isAnySyncing = isSyncing;

                // Determine elapsed time to display while this credential is syncing.
                const activeSyncKeys: string[] = isSyncing ? [cred.id] : [];
                const maxElapsed =
                  activeSyncKeys.length > 0
                    ? Math.max(...activeSyncKeys.map((k) => elapsedSeconds[k] ?? 0))
                    : 0;

                const hasPasswordChangeError =
                  syncState?.error?.toLowerCase().includes('password change') ?? false;
                const credentialSummary = buildSyncSummary(syncedAccounts, cred);
                const credentialSyncingDomains = new Set<SyncDomain>();
                if (isSyncing) {
                  SYNC_DOMAINS.forEach((domain) => credentialSyncingDomains.add(domain.key));
                }

                return (
                  <li key={cred.id} className="py-4 first:pt-0 last:pb-0">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                      {/* Bank info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {cred.label ?? (BANK_LABELS[cred.bank as Bank] ?? cred.bank)}
                        </p>
                        <p className="mt-0.5 break-words text-xs text-gray-500 dark:text-gray-400">
                          {BANK_LABELS[cred.bank as Bank] ?? cred.bank} &middot; Last synced: {formatDate(cred.last_synced_at)}
                        </p>
                        {/* Sync feedback */}
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
                        {/* Password change warning */}
                        {hasPasswordChangeError && (
                          <div className="mt-2 flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700">
                            <svg className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                            </svg>
                            <p className="text-xs text-amber-700 dark:text-amber-300">
                              Your bank requires a password change. Update your credentials below to continue syncing.
                            </p>
                          </div>
                        )}
                        <div className="mt-3 max-w-md">
                          <SyncCoverageBar
                            summary={credentialSummary}
                            syncingDomains={credentialSyncingDomains}
                          />
                        </div>
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
                      <div className="flex flex-wrap items-center gap-2 sm:shrink-0 sm:justify-end">
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={isSyncing}
                          disabled={isSyncing || isRemoving}
                          onClick={() => void handleSync(cred)}
                        >
                          Sync All
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={isAnySyncing || isRemoving || updating}
                          onClick={() => {
                            if (editingId === cred.id) {
                              setEditingId(null);
                            } else {
                              setEditingId(cred.id);
                              setEditLabel(cred.label ?? '');
                              setEditUsername('');
                              setEditPassword('');
                              setUpdateError(null);
                            }
                          }}
                        >
                          {editingId === cred.id ? 'Cancel' : 'Edit'}
                        </Button>
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
                    {/* Inline edit form */}
                    {editingId === cred.id && (
                      <div className="mt-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 space-y-3">
                        <p className="text-xs font-medium text-gray-700 dark:text-gray-300">
                          Update credentials - leave blank to keep existing value
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <Input
                            label="New Username (optional)"
                            placeholder="Leave blank to keep current"
                            autoComplete="off"
                            value={editUsername}
                            onChange={(e) => setEditUsername(e.target.value)}
                          />
                          <Input
                            label="New Password (optional)"
                            type="password"
                            placeholder="Leave blank to keep current"
                            autoComplete="new-password"
                            value={editPassword}
                            onChange={(e) => setEditPassword(e.target.value)}
                          />
                        </div>
                        <Input
                          label="Label / Nickname (optional)"
                          placeholder="e.g. Personal NBE"
                          autoComplete="off"
                          value={editLabel}
                          onChange={(e) => setEditLabel(e.target.value)}
                        />
                        {updateError && (
                          <p className="text-xs text-red-600 dark:text-red-400">{updateError}</p>
                        )}
                        <div className="flex justify-end">
                          <Button
                            size="sm"
                            className="w-full sm:w-auto"
                            loading={updating}
                            disabled={updating}
                            onClick={() => void handleUpdate(cred)}
                          >
                            Save Changes
                          </Button>
                        </div>
                      </div>
                    )}
                    {activeSyncKeys.length > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                        Syncing... {maxElapsed}s - this can take 2-4 minutes
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
                className="w-full sm:w-auto"
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
