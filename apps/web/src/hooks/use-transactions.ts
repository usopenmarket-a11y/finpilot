'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Transaction } from '@/lib/types';

export interface TransactionFilters {
  search: string;
  category: string;
  type: 'all' | 'debit' | 'credit';
  dateFrom: string;
  dateTo: string;
}

interface UseTransactionsResult {
  transactions: Transaction[];
  loading: boolean;
  error: string | null;
  filters: TransactionFilters;
  setFilters: (filters: Partial<TransactionFilters>) => void;
  refetch: () => void;
}

const DEFAULT_FILTERS: TransactionFilters = {
  search: '',
  category: '',
  type: 'all',
  dateFrom: '',
  dateTo: '',
};

export function useTransactions(): UseTransactionsResult {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<TransactionFilters>(DEFAULT_FILTERS);

  const setFilters = useCallback((partial: Partial<TransactionFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...partial }));
  }, []);

  const fetchTransactions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filters.search) params.set('search', filters.search);
      if (filters.category) params.set('category', filters.category);
      if (filters.type !== 'all') params.set('type', filters.type);
      if (filters.dateFrom) params.set('date_from', filters.dateFrom);
      if (filters.dateTo) params.set('date_to', filters.dateTo);

      const query = params.toString();
      const data = await api.get<Transaction[]>(
        `/transactions${query ? `?${query}` : ''}`
      );
      setTransactions(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load transactions';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchTransactions();
  }, [fetchTransactions]);

  return { transactions, loading, error, filters, setFilters, refetch: fetchTransactions };
}
