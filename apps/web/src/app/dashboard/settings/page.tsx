'use client';

import { useState, useEffect } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardBody } from '@/components/ui/card';
import { BankAccountsSection } from '@/components/settings/bank-accounts-section';

export default function SettingsPage() {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  useEffect(() => {
    const supabase = createClient();
    void supabase.auth.getUser().then((result: { data: { user: { email?: string; user_metadata: Record<string, unknown> } | null } }) => {
      const user = result.data.user;
      if (user) {
        setEmail(user.email ?? '');
        const name = typeof user.user_metadata?.display_name === 'string'
          ? user.user_metadata.display_name
          : '';
        setDisplayName(name);
      }
    });
  }, []);

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
    <div className="p-6 lg:p-8 space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Manage your account and preferences
        </p>
      </div>

      {/* Profile section */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Profile</h2>
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
                    ? 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                    : 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
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

      {/* Bank Accounts section */}
      <BankAccountsSection />
    </div>
  );
}
