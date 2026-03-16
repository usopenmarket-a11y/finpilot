"""API request/response Pydantic v2 schemas.

These are the wire-format models that appear in FastAPI route signatures.
They are distinct from the DB-mirror models in db.py so that the API
contract can evolve independently of the persistence layer.

Naming convention:
  <Entity>Request   — inbound payload (POST/PUT body)
  <Entity>Response  — outbound payload
  <Entity>Update    — partial-update payload (PATCH body); all fields Optional
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from app.models.db import UserProfile

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class SignUpRequest(BaseModel):
    """Body for POST /auth/sign-up."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(description="User's email address — used as the login identifier")
    # SecretStr prevents the password from appearing in logs, tracebacks, or
    # Pydantic repr output.  Call .get_secret_value() only at the point of use
    # (i.e. when passing to the Supabase auth client).
    password: SecretStr = Field(
        min_length=8,
        description="Password (transmitted over TLS, never persisted in plaintext)",
    )
    full_name: str | None = Field(
        default=None,
        max_length=120,
        description="Optional display name stored in public.user_profiles",
    )


class SignInRequest(BaseModel):
    """Body for POST /auth/sign-in."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(description="Registered email address")
    # SecretStr prevents the password from appearing in logs, tracebacks, or
    # Pydantic repr output.  Call .get_secret_value() only at the point of use.
    password: SecretStr = Field(description="Account password")


class AuthResponse(BaseModel):
    """Successful authentication response — contains JWTs and the user profile."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(
        description="Short-lived JWT access token — include in Authorization: Bearer <token>"
    )
    refresh_token: str = Field(
        description="Long-lived refresh token — use to obtain a new access token"
    )
    user: UserProfile = Field(description="Authenticated user's profile data")


class MessageResponse(BaseModel):
    """Generic single-message envelope used for confirmations and errors."""

    message: str = Field(description="Human-readable status or error message")


# ---------------------------------------------------------------------------
# Bank account API schemas
# ---------------------------------------------------------------------------


class BankAccountCreate(BaseModel):
    """Body for POST /accounts — register a new bank account."""

    bank_name: str = Field(description="One of: NBE, CIB, BDC, UB")
    account_number_masked: str = Field(
        description="Last 4 digits only — never send or store the full account number"
    )
    account_type: str = Field(description="One of: savings, current, credit, loan")
    currency: str = Field(default="EGP", description="ISO 4217 currency code")


class BankAccountUpdate(BaseModel):
    """Body for PATCH /accounts/{id} — all fields optional."""

    account_type: str | None = Field(default=None, description="Updated account type")
    currency: str | None = Field(default=None, description="Updated currency code")
    is_active: bool | None = Field(default=None, description="Toggle active/inactive sync")


# ---------------------------------------------------------------------------
# Debt API schemas
# ---------------------------------------------------------------------------


class DebtCreate(BaseModel):
    """Body for POST /debts — create a new manual debt entry."""

    debt_type: str = Field(description="One of: lent, borrowed")
    counterparty_name: str = Field(description="Name of the other party")
    counterparty_phone: str | None = Field(default=None, description="Contact phone number")
    counterparty_email: str | None = Field(default=None, description="Contact email")
    original_amount: float = Field(gt=0, description="Initial debt amount — must be positive")
    currency: str = Field(default="EGP", description="ISO 4217 currency code")
    due_date: str | None = Field(
        default=None, description="ISO 8601 date string (YYYY-MM-DD) for the repayment deadline"
    )
    notes: str | None = Field(default=None, description="Free-text context")


class DebtUpdate(BaseModel):
    """Body for PATCH /debts/{id}."""

    counterparty_phone: str | None = None
    counterparty_email: str | None = None
    due_date: str | None = None
    notes: str | None = None
    status: str | None = None


class DebtPaymentCreate(BaseModel):
    """Body for POST /debts/{id}/payments — record a repayment event."""

    amount: float = Field(gt=0, description="Payment amount — must be positive")
    payment_date: str = Field(description="ISO 8601 date string (YYYY-MM-DD)")
    notes: str | None = Field(default=None, description="Optional payment memo")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PaginatedResponse(BaseModel):
    """Generic pagination envelope — wrap any list response in this."""

    total: int = Field(description="Total number of records matching the query")
    page: int = Field(ge=1, description="Current page number (1-based)")
    page_size: int = Field(ge=1, le=100, description="Number of records per page")
    data: list = Field(description="Page of records")
