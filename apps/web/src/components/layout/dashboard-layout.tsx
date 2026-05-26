import { type ReactNode } from 'react';
import { Sidebar } from './sidebar';

interface DashboardLayoutProps {
  children: ReactNode;
  userEmail: string;
}

export function DashboardLayout({ children, userEmail }: DashboardLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-950 lg:flex-row">
      <Sidebar userEmail={userEmail} />
      <main className="w-full flex-1 min-w-0 overflow-x-hidden overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
