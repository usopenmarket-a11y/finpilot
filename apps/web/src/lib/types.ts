export interface Debt {
  id: string;
  debt_type: 'lent' | 'borrowed';
  counterparty_name: string;
  outstanding_balance: number;
  original_amount: number;
  currency: string;
  status: 'active' | 'partial' | 'settled';
  due_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface DebtPayment {
  id: string;
  debt_id: string;
  amount: number;
  payment_date: string;
  notes: string | null;
  created_at: string;
}

export interface Transaction {
  id: string;
  description: string;
  amount: number;
  transaction_type: 'debit' | 'credit';
  transaction_date: string;
  category: string | null;
  currency: string;
}

export interface ActionItem {
  priority: 'high' | 'medium' | 'low';
  category: string;
  title: string;
  description: string;
  estimated_impact: number;
}

export interface MonthlyPlan {
  month: number;
  year: number;
  summary: string;
  action_items: ActionItem[];
  projected_savings: number;
  health_score: number;
}

export interface SavingsOpportunity {
  opportunity_type: string;
  title: string;
  description: string;
  estimated_monthly_saving: number;
}

export interface ForecastPoint {
  year: number;
  month: number;
  projected_income: number;
  projected_expenses: number;
  projected_net: number;
}
