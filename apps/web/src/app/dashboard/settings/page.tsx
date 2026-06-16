'use client';

import { useState, useEffect } from 'react';
import { createClient } from '@/lib/supabase/client';
import {
  clearData,
  getPreferences,
  savePreferences,
  type ClearDataScope,
} from '@/lib/api-client';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardBody } from '@/components/ui/card';
import { BankAccountsSection } from '@/components/settings/bank-accounts-section';

export default function SettingsPage() {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [clearingScope, setClearingScope] = useState<ClearDataScope | null>(null);
  const [confirmScope, setConfirmScope] = useState<ClearDataScope | null>(null);
  const [clearMsg, setClearMsg] = useState<string | null>(null);

  // Credit card preferences
  const [fawryRatePct, setFawryRatePct] = useState('1');
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [prefsMsg, setPrefsMsg] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient();
    void supabase.auth.getSession().then(async (result: { data: { session: { access_token: string; user: { id: string; email?: string; user_metadata: Record<string, unknown> } } | null } }) => {
      const session = result.data.session;
      if (session) {
        const user = session.user;
        setAccessToken(session.access_token);
        setEmail(user.email ?? '');
        const name = typeof user.user_metadata?.display_name === 'string'
          ? user.user_metadata.display_name
          : '';
        setDisplayName(name);

        try {
          const prefs = await getPreferences(session.access_token);
          if (typeof prefs.fawry_rate === 'number') {
            setFawryRatePct((prefs.fawry_rate * 100).toFixed(2));
          }
        } catch {
          // Keep the default preference value if the API is unavailable.
        }
      }
    });
  }, []);

  const handleSavePreferences = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!accessToken) return;
    setSavingPrefs(true);
    setPrefsMsg(null);
    try {
      const rate = parseFloat(fawryRatePct);
      if (isNaN(rate) || rate < 0 || rate > 100) throw new Error('Enter a valid percentage between 0 and 100');
      await savePreferences(accessToken, { fawry_rate: rate / 100 });
      setPrefsMsg('Preferences saved.');
    } catch (err) {
      setPrefsMsg(err instanceof Error ? err.message : 'Failed to save preferences.');
    } finally {
      setSavingPrefs(false);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveMsg(null);

    try {
      const supabase = createClient();
      const { error } = await supabase.auth.updateUser({
        data: { display_name: displayName.trim() },
      });
      if (error) throw error;
      setSaveMsg('Profile saved successfully.');
    } catch {
      setSaveMsg('Failed to save profile. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-ink">Settings</h1>
        <p className="text-sm text-ink-muted mt-1">
          Manage your account and preferences
        </p>
      </div>

      {/* Profile + Preferences — side by side on large screens to use the width */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Profile section */}
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold text-ink">Profile</h2>
          </CardHeader>
          <CardBody>
            <form onSubmit={handleSaveProfile} className="flex flex-col gap-4">
              <Input
                label="Display Name"
                placeholder="Your name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
              <Input
                label="Email Address"
                type="email"
                value={email}
                readOnly
                disabled
                helperText="Email cannot be changed here."
              />
              {saveMsg && (
                <p
                  className={`text-sm px-3 py-2 rounded-lg ${
                    saveMsg.startsWith('Failed')
                      ? 'text-negative bg-negative-soft'
                      : 'text-positive bg-positive-soft'
                  }`}
                >
                  {saveMsg}
                </p>
              )}
              <div className="flex justify-end">
                <Button type="submit" loading={saving}>
                  Save Profile
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>

        {/* Credit Card Preferences */}
        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold text-ink">Credit Card Preferences</h2>
          </CardHeader>
          <CardBody>
            <form onSubmit={handleSavePreferences} className="flex flex-col gap-4">
              <Input
                label="Fawry Interest Rate (%)"
                type="number"
                value={fawryRatePct}
                onChange={(e) => setFawryRatePct(e.target.value)}
                min="0"
                max="100"
                step="0.01"
                helperText="Applied to Fawry charges in the Repayment Tracker (e.g. 1 for 1%)"
              />
              {prefsMsg && (
                <p className={`text-sm px-3 py-2 rounded-lg ${
                  prefsMsg.startsWith('Failed') || prefsMsg.startsWith('Enter')
                    ? 'text-negative bg-negative-soft'
                    : 'text-positive bg-positive-soft'
                }`}>
                  {prefsMsg}
                </p>
              )}
              <div className="flex justify-end">
                <Button type="submit" loading={savingPrefs}>Save Preferences</Button>
              </div>
            </form>
          </CardBody>
        </Card>
      </div>

      {/* Bank Accounts section */}
      <BankAccountsSection />

      {/* Danger Zone */}
      <Card className="border-negative/40">
        <CardHeader>
          <h2 className="text-base font-semibold text-negative">Danger Zone</h2>
        </CardHeader>
        <CardBody className="space-y-3">
          <p className="text-xs text-ink-muted">
            Clear specific data categories. Credentials are never removed. Re-sync after clearing to repopulate.
          </p>
          {(
            [
              { scope: 'accounts', label: 'Accounts', desc: 'Savings, current & payroll accounts + transactions' },
              { scope: 'credit_cards', label: 'Credit Cards', desc: 'Credit card accounts + transactions' },
              { scope: 'certificates', label: 'Certificates & Deposits', desc: 'Certificate and deposit accounts' },
              { scope: 'debts', label: 'Debts', desc: 'Manually entered borrowing & lending records' },
              { scope: 'installments', label: 'Installments', desc: 'BNPL plans and instalment obligations' },
            ] as { scope: ClearDataScope; label: string; desc: string }[]
          ).map(({ scope, label, desc }) => (
            <div key={scope} className="flex flex-col sm:flex-row sm:items-center gap-2 py-2 border-t border-line first:border-t-0 first:pt-0">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink">{label}</p>
                <p className="text-xs text-ink-muted">{desc}</p>
              </div>
              {confirmScope !== scope ? (
                <Button
                  variant="danger"
                  size="sm"
                  disabled={clearingScope !== null}
                  onClick={() => { setConfirmScope(scope); setClearMsg(null); }}
                >
                  Clear
                </Button>
              ) : (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-ink-muted whitespace-nowrap">Sure?</span>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={clearingScope === scope}
                    disabled={clearingScope !== null}
                    onClick={async () => {
                      if (!accessToken) return;
                      setClearingScope(scope);
                      setClearMsg(null);
                      try {
                        await clearData(accessToken, scope);
                        setClearMsg(`${label} cleared successfully.`);
                        setConfirmScope(null);
                      } catch {
                        setClearMsg(`Failed to clear ${label}. Please try again.`);
                      } finally {
                        setClearingScope(null);
                      }
                    }}
                  >
                    Yes
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={clearingScope !== null}
                    onClick={() => setConfirmScope(null)}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          ))}
          {clearMsg && (
            <p className={`text-xs px-3 py-2 rounded-lg ${
              clearMsg.startsWith('Failed')
                ? 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                : 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
            }`}>
              {clearMsg}
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
