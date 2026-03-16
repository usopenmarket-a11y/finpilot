'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Debt } from '@/lib/types';

interface UseDebtsResult {
  debts: Debt[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useDebts(): UseDebtsResult {
  const [debts, setDebts] = useState<Debt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDebts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Debt[]>('/debts');
      setDebts(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load debts';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDebts();
  }, [fetchDebts]);

  return { debts, loading, error, refetch: fetchDebts };
}
