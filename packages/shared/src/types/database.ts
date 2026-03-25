// AUTO-GENERATED — do not edit manually.
// Regenerate with: Supabase MCP → generate_typescript_types
// Last generated: 2026-03-25

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.4"
  }
  public: {
    Tables: {
      bank_accounts: {
        Row: {
          account_number_masked: string
          account_type: string
          balance: number
          bank_name: string
          billed_amount: number | null
          created_at: string
          credit_limit: number | null
          currency: string
          id: string
          interest_rate: number | null
          is_active: boolean
          last_synced_at: string | null
          maturity_date: string | null
          minimum_payment: number | null
          opened_date: string | null
          payment_due_date: string | null
          product_name: string | null
          unbilled_amount: number | null
          updated_at: string
          user_id: string
        }
        Insert: {
          account_number_masked: string
          account_type: string
          balance?: number
          bank_name: string
          billed_amount?: number | null
          created_at?: string
          credit_limit?: number | null
          currency?: string
          id?: string
          interest_rate?: number | null
          is_active?: boolean
          last_synced_at?: string | null
          maturity_date?: string | null
          minimum_payment?: number | null
          opened_date?: string | null
          payment_due_date?: string | null
          product_name?: string | null
          unbilled_amount?: number | null
          updated_at?: string
          user_id: string
        }
        Update: {
          account_number_masked?: string
          account_type?: string
          balance?: number
          bank_name?: string
          billed_amount?: number | null
          created_at?: string
          credit_limit?: number | null
          currency?: string
          id?: string
          interest_rate?: number | null
          is_active?: boolean
          last_synced_at?: string | null
          maturity_date?: string | null
          minimum_payment?: number | null
          opened_date?: string | null
          payment_due_date?: string | null
          product_name?: string | null
          unbilled_amount?: number | null
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      bank_credentials: {
        Row: {
          bank: string
          created_at: string
          encrypted_password: string
          encrypted_username: string
          id: string
          is_active: boolean
          label: string | null
          last_synced_at: string | null
          updated_at: string
          user_id: string
        }
        Insert: {
          bank: string
          created_at?: string
          encrypted_password: string
          encrypted_username: string
          id?: string
          is_active?: boolean
          label?: string | null
          last_synced_at?: string | null
          updated_at?: string
          user_id: string
        }
        Update: {
          bank?: string
          created_at?: string
          encrypted_password?: string
          encrypted_username?: string
          id?: string
          is_active?: boolean
          label?: string | null
          last_synced_at?: string | null
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      debt_payments: {
        Row: {
          amount: number
          created_at: string
          debt_id: string
          id: string
          notes: string | null
          payment_date: string
        }
        Insert: {
          amount: number
          created_at?: string
          debt_id: string
          id?: string
          notes?: string | null
          payment_date: string
        }
        Update: {
          amount?: number
          created_at?: string
          debt_id?: string
          id?: string
          notes?: string | null
          payment_date?: string
        }
        Relationships: [
          {
            foreignKeyName: "debt_payments_debt_id_fkey"
            columns: ["debt_id"]
            isOneToOne: false
            referencedRelation: "debts"
            referencedColumns: ["id"]
          },
        ]
      }
      debts: {
        Row: {
          counterparty_email: string | null
          counterparty_name: string
          counterparty_phone: string | null
          created_at: string
          currency: string
          debt_type: string
          due_date: string | null
          id: string
          notes: string | null
          original_amount: number
          outstanding_balance: number
          status: string
          updated_at: string
          user_id: string
        }
        Insert: {
          counterparty_email?: string | null
          counterparty_name: string
          counterparty_phone?: string | null
          created_at?: string
          currency?: string
          debt_type: string
          due_date?: string | null
          id?: string
          notes?: string | null
          original_amount: number
          outstanding_balance: number
          status?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          counterparty_email?: string | null
          counterparty_name?: string
          counterparty_phone?: string | null
          created_at?: string
          currency?: string
          debt_type?: string
          due_date?: string | null
          id?: string
          notes?: string | null
          original_amount?: number
          outstanding_balance?: number
          status?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      installments: {
        Row: {
          billing_day: number | null
          category: string
          created_at: string
          down_payment: number
          id: string
          is_active: boolean
          monthly_amount: number
          name: string
          notes: string | null
          start_date: string
          total_amount: number
          total_months: number
          updated_at: string
          user_id: string
        }
        Insert: {
          billing_day?: number | null
          category: string
          created_at?: string
          down_payment?: number
          id?: string
          is_active?: boolean
          monthly_amount: number
          name: string
          notes?: string | null
          start_date: string
          total_amount: number
          total_months: number
          updated_at?: string
          user_id: string
        }
        Update: {
          billing_day?: number | null
          category?: string
          created_at?: string
          down_payment?: number
          id?: string
          is_active?: boolean
          monthly_amount?: number
          name?: string
          notes?: string | null
          start_date?: string
          total_amount?: number
          total_months?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      loans: {
        Row: {
          account_id: string
          created_at: string
          id: string
          interest_rate: number
          loan_type: string
          maturity_date: string | null
          monthly_installment: number
          next_payment_date: string | null
          outstanding_balance: number
          principal_amount: number
          updated_at: string
          user_id: string
        }
        Insert: {
          account_id: string
          created_at?: string
          id?: string
          interest_rate: number
          loan_type: string
          maturity_date?: string | null
          monthly_installment: number
          next_payment_date?: string | null
          outstanding_balance: number
          principal_amount: number
          updated_at?: string
          user_id: string
        }
        Update: {
          account_id?: string
          created_at?: string
          id?: string
          interest_rate?: number
          loan_type?: string
          maturity_date?: string | null
          monthly_installment?: number
          next_payment_date?: string | null
          outstanding_balance?: number
          principal_amount?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "loans_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "bank_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      transactions: {
        Row: {
          account_id: string
          amount: number
          balance_after: number | null
          category: string | null
          created_at: string
          currency: string
          description: string
          external_id: string
          id: string
          is_categorized: boolean
          raw_data: Json
          sub_category: string | null
          transaction_date: string
          transaction_type: string
          updated_at: string
          user_id: string
          value_date: string | null
        }
        Insert: {
          account_id: string
          amount: number
          balance_after?: number | null
          category?: string | null
          created_at?: string
          currency?: string
          description: string
          external_id: string
          id?: string
          is_categorized?: boolean
          raw_data?: Json
          sub_category?: string | null
          transaction_date: string
          transaction_type: string
          updated_at?: string
          user_id: string
          value_date?: string | null
        }
        Update: {
          account_id?: string
          amount?: number
          balance_after?: number | null
          category?: string | null
          created_at?: string
          currency?: string
          description?: string
          external_id?: string
          id?: string
          is_categorized?: boolean
          raw_data?: Json
          sub_category?: string | null
          transaction_date?: string
          transaction_type?: string
          updated_at?: string
          user_id?: string
          value_date?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "transactions_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "bank_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      user_profiles: {
        Row: {
          created_at: string
          full_name: string | null
          id: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          full_name?: string | null
          id: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          full_name?: string | null
          id?: string
          updated_at?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
