"""DB-mirror Pydantic v2 models.

Each model reflects a single database table and is used for type-safe
serialisation/deserialisation of rows returned from Supabase.  These are
*read* models — they are never used directly for writes; use the router-layer
request schemas in api.py for that purpose.

All monetary amounts are represented as Decimal to avoid floating-point
rounding errors.  All IDs are UUID.  All timestamps are timezone-aware
datetime objects (TIMESTAMPTZ on the DB side).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


class UserProfile(BaseModel):
    """Mirrors public.user_profiles — extends auth.users with display info."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="FK to auth.users(id) — same value as the Supabase user UID")
    full_name: Optional[str] = Field(default=None, description="User's display name")
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
    updated_at: datetime = Field(description="Last modification timestamp (TIMESTAMPTZ)")


# ---------------------------------------------------------------------------
# Bank account
# ---------------------------------------------------------------------------

SUPPORTED_BANKS = ("NBE", "CIB", "BDC", "UB")
ACCOUNT_TYPES = ("savings", "current", "credit", "loan")


class BankAccount(BaseModel):
    """Mirrors public.bank_accounts."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Primary key — gen_random_uuid()")
    user_id: UUID = Field(description="FK to auth.users(id)")
    bank_name: str = Field(description="Supported bank identifier — one of: NBE, CIB, BDC, UB")
    account_number_masked: str = Field(
        description="Last 4 digits of the account number (never store full number)"
    )
    account_type: str = Field(
        description="Account classification — one of: savings, current, credit, loan"
    )
    currency: str = Field(default="EGP", description="ISO 4217 currency code")
    balance: Decimal = Field(description="Current account balance (NUMERIC 15,2)")
    is_active: bool = Field(default=True, description="Whether the account is actively synced")
    last_synced_at: Optional[datetime] = Field(
        default=None, description="Timestamp of the most recent successful scrape"
    )
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
    updated_at: datetime = Field(description="Last modification timestamp (TIMESTAMPTZ)")


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

TRANSACTION_TYPES = ("debit", "credit")


class Transaction(BaseModel):
    """Mirrors public.transactions.

    The (account_id, external_id) pair is UNIQUE — this is the deduplication
    key used by the pipeline layer to prevent double-inserts.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Primary key — gen_random_uuid()")
    user_id: UUID = Field(description="FK to auth.users(id) — denormalised for fast RLS checks")
    account_id: UUID = Field(description="FK to public.bank_accounts(id)")
    external_id: str = Field(
        description="Bank-assigned transaction reference — used for deduplication"
    )
    amount: Decimal = Field(description="Transaction amount (NUMERIC 15,2). Always positive.")
    currency: str = Field(default="EGP", description="ISO 4217 currency code")
    transaction_type: str = Field(
        description="Direction of money flow — one of: debit, credit"
    )
    description: str = Field(description="Raw description text extracted from the bank statement")
    category: Optional[str] = Field(
        default=None, description="Top-level AI-assigned spending category"
    )
    sub_category: Optional[str] = Field(
        default=None, description="Granular AI-assigned spending sub-category"
    )
    transaction_date: date = Field(description="Date the transaction was posted")
    value_date: Optional[date] = Field(
        default=None, description="Value date (settlement date) where provided by the bank"
    )
    balance_after: Optional[Decimal] = Field(
        default=None, description="Account balance immediately after this transaction"
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original scraped payload stored as JSONB for audit/re-processing",
    )
    is_categorized: bool = Field(
        default=False, description="True once the AI categorization pass has completed"
    )
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
    updated_at: datetime = Field(description="Last modification timestamp (TIMESTAMPTZ)")


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------

LOAN_TYPES = ("personal", "mortgage", "auto", "overdraft")


class Loan(BaseModel):
    """Mirrors public.loans — bank-originated credit facilities linked to an account."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Primary key — gen_random_uuid()")
    user_id: UUID = Field(description="FK to auth.users(id)")
    account_id: UUID = Field(description="FK to public.bank_accounts(id)")
    loan_type: str = Field(
        description="Loan classification — one of: personal, mortgage, auto, overdraft"
    )
    principal_amount: Decimal = Field(description="Original loan principal (NUMERIC 15,2)")
    outstanding_balance: Decimal = Field(
        description="Remaining balance to be repaid (NUMERIC 15,2)"
    )
    interest_rate: Decimal = Field(
        description="Annual interest rate as a decimal fraction, e.g. 0.1850 = 18.50% (NUMERIC 6,4)"
    )
    monthly_installment: Decimal = Field(
        description="Fixed monthly repayment amount (NUMERIC 15,2)"
    )
    next_payment_date: Optional[date] = Field(
        default=None, description="Date the next installment is due"
    )
    maturity_date: Optional[date] = Field(
        default=None, description="Date on which the loan is fully repaid"
    )
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
    updated_at: datetime = Field(description="Last modification timestamp (TIMESTAMPTZ)")


# ---------------------------------------------------------------------------
# Debt (manual borrowing/lending tracker)
# ---------------------------------------------------------------------------

DEBT_TYPES = ("lent", "borrowed")
DEBT_STATUSES = ("active", "partial", "settled")


class Debt(BaseModel):
    """Mirrors public.debts — user-managed ledger for informal borrowing and lending."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Primary key — gen_random_uuid()")
    user_id: UUID = Field(description="FK to auth.users(id)")
    debt_type: str = Field(
        description="Whether the user lent money ('lent') or borrowed it ('borrowed')"
    )
    counterparty_name: str = Field(description="Name of the person money was lent to/borrowed from")
    counterparty_phone: Optional[str] = Field(
        default=None, description="Optional contact phone number for the counterparty"
    )
    counterparty_email: Optional[str] = Field(
        default=None, description="Optional contact email for the counterparty"
    )
    original_amount: Decimal = Field(description="Initial debt amount (NUMERIC 15,2)")
    outstanding_balance: Decimal = Field(
        description="Remaining unpaid amount — reduced as payments are recorded (NUMERIC 15,2)"
    )
    currency: str = Field(default="EGP", description="ISO 4217 currency code")
    due_date: Optional[date] = Field(
        default=None, description="Agreed repayment deadline (if any)"
    )
    notes: Optional[str] = Field(
        default=None, description="Free-text context (e.g. purpose of the loan)"
    )
    status: str = Field(
        default="active",
        description="Settlement state — one of: active, partial, settled",
    )
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
    updated_at: datetime = Field(description="Last modification timestamp (TIMESTAMPTZ)")


class DebtPayment(BaseModel):
    """Mirrors public.debt_payments — individual repayment events against a Debt record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Primary key — gen_random_uuid()")
    debt_id: UUID = Field(description="FK to public.debts(id)")
    amount: Decimal = Field(description="Amount paid in this instalment (NUMERIC 15,2)")
    payment_date: date = Field(description="Calendar date the payment was made")
    notes: Optional[str] = Field(
        default=None, description="Optional memo for this specific payment"
    )
    created_at: datetime = Field(description="Row creation timestamp (TIMESTAMPTZ)")
