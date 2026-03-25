import { createClient } from '@/lib/supabase/server';
import { InstallmentsClient } from '@/components/installments/installments-client';
import type { Database } from '@finpilot/shared';

export const dynamic = 'force-dynamic';

type InstallmentRow = Database['public']['Tables']['installments']['Row'];

export default async function InstallmentsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const { data } = await supabase
    .from('installments')
    .select('*')
    .eq('user_id', userId)
    .eq('is_active', true)
    .order('start_date', { ascending: false });

  const items: InstallmentRow[] = data ?? [];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Installments</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Track BNPL plans, home loans, and other recurring monthly obligations
        </p>
      </div>

      <InstallmentsClient initialItems={items} />
    </div>
  );
}
