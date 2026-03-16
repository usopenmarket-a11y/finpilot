'use client';

import { useState, useEffect } from 'react';
import { createClient } from '@/lib/supabase/client';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardBody } from '@/components/ui/card';

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
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            Connected Bank Accounts
          </h2>
        </CardHeader>
        <CardBody>
          <div className="flex flex-col items-center py-8 gap-3">
            <div className="p-3 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-400">
              <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center max-w-xs">
              No bank accounts connected yet. Connect your Egyptian bank accounts to start aggregating data.
            </p>
            <div className="relative group">
              <Button disabled>
                Connect Bank Account
              </Button>
              {/* "Coming Soon" tooltip */}
              <div
                className="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-3 py-1.5 rounded-lg bg-gray-900 dark:bg-gray-700 text-white text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity"
                role="tooltip"
              >
                Coming Soon
                <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-x-4 border-x-transparent border-t-4 border-t-gray-900 dark:border-t-gray-700" />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
