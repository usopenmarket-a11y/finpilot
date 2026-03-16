import { redirect } from 'next/navigation';
import { type ReactNode } from 'react';
import { createClient } from '@/lib/supabase/server';
import { DashboardLayout } from '@/components/layout/dashboard-layout';

export default async function Layout({ children }: { children: ReactNode }) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect('/auth/login');
  }

  return (
    <DashboardLayout userEmail={user.email ?? ''}>
      {children}
    </DashboardLayout>
  );
}
