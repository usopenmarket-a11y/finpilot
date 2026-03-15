"""Unit tests for Pydantic v2 models in app.models.db and app.models.api.

These are pure unit tests — no ASGI app, no network, no DB.  Each test
instantiates a model directly and asserts on field values, defaults, and
validation behaviour.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Return a timezone-aware UTC datetime for use in model fixtures."""
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return date.today()


# ---------------------------------------------------------------------------
# app.models.api — SignUpRequest
# ---------------------------------------------------------------------------


def test_signup_request_valid_minimal() -> None:
    """Minimal valid SignUpRequest with no optional fields."""
    from app.models.api import SignUpRequest

    req = SignUpRequest(email="test@example.com", password="secret123")
    assert req.email == "test@example.com"
    assert req.password.get_secret_value() == "secret123"
    assert req.full_name is None


def test_signup_request_with_full_name() -> None:
    """Optional full_name is stored when supplied."""
    from app.models.api import SignUpRequest

    req = SignUpRequest(
        email="test@example.com",
        password="secret123",
        full_name="John Doe",
    )
    assert req.full_name == "John Doe"


def test_signup_request_invalid_email() -> None:
    """A non-email string must raise ValidationError."""
    from app.models.api import SignUpRequest

    with pytest.raises(ValidationError):
        SignUpRequest(email="not-an-email", password="secret123")


def test_signup_request_password_too_short() -> None:
    """Password shorter than 8 characters must raise ValidationError."""
    from app.models.api import SignUpRequest

    with pytest.raises(ValidationError):
        SignUpRequest(email="test@example.com", password="short")


def test_signup_request_missing_required_fields() -> None:
    """Omitting required fields must raise ValidationError."""
    from app.models.api import SignUpRequest

    with pytest.raises(ValidationError):
        SignUpRequest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# app.models.api — SignInRequest
# ---------------------------------------------------------------------------


def test_signin_request_valid() -> None:
    """Valid sign-in request round-trips without error."""
    from app.models.api import SignInRequest

    req = SignInRequest(email="user@example.com", password="any_password")
    assert req.email == "user@example.com"


def test_signin_request_invalid_email() -> None:
    """Non-email value must raise ValidationError."""
    from app.models.api import SignInRequest

    with pytest.raises(ValidationError):
        SignInRequest(email="bad", password="password")


# ---------------------------------------------------------------------------
# app.models.api — DebtCreate
# ---------------------------------------------------------------------------


def test_debt_create_valid() -> None:
    """Valid DebtCreate with minimal required fields."""
    from app.models.api import DebtCreate

    debt = DebtCreate(
        debt_type="lent",
        counterparty_name="Ahmed",
        original_amount=500.0,
    )
    assert debt.currency == "EGP"
    assert debt.counterparty_phone is None
    assert debt.counterparty_email is None
    assert debt.due_date is None


def test_debt_create_amount_must_be_positive() -> None:
    """original_amount <= 0 must raise ValidationError (gt=0 constraint)."""
    from app.models.api import DebtCreate

    with pytest.raises(ValidationError):
        DebtCreate(debt_type="borrowed", counterparty_name="Sara", original_amount=0.0)

    with pytest.raises(ValidationError):
        DebtCreate(debt_type="borrowed", counterparty_name="Sara", original_amount=-100.0)


def test_debt_create_optional_contact_fields() -> None:
    """Optional phone/email/notes/due_date fields are accepted."""
    from app.models.api import DebtCreate

    debt = DebtCreate(
        debt_type="borrowed",
        counterparty_name="Khalid",
        original_amount=1000.0,
        counterparty_phone="+201001234567",
        counterparty_email="khalid@example.com",
        due_date="2026-06-30",
        notes="Emergency loan",
    )
    assert debt.counterparty_phone == "+201001234567"
    assert debt.notes == "Emergency loan"


# ---------------------------------------------------------------------------
# app.models.api — DebtPaymentCreate
# ---------------------------------------------------------------------------


def test_debt_payment_create_valid() -> None:
    """Valid payment with positive amount."""
    from app.models.api import DebtPaymentCreate

    payment = DebtPaymentCreate(amount=250.0, payment_date="2026-03-15")
    assert payment.amount == 250.0
    assert payment.notes is None


def test_debt_payment_create_amount_must_be_positive() -> None:
    """amount <= 0 must raise ValidationError."""
    from app.models.api import DebtPaymentCreate

    with pytest.raises(ValidationError):
        DebtPaymentCreate(amount=0.0, payment_date="2026-03-15")


# ---------------------------------------------------------------------------
# app.models.api — BankAccountCreate / BankAccountUpdate
# ---------------------------------------------------------------------------


def test_bank_account_create_defaults() -> None:
    """BankAccountCreate defaults currency to EGP."""
    from app.models.api import BankAccountCreate

    acct = BankAccountCreate(
        bank_name="NBE",
        account_number_masked="****1234",
        account_type="savings",
    )
    assert acct.currency == "EGP"


def test_bank_account_update_all_optional() -> None:
    """BankAccountUpdate can be constructed with no fields (all optional)."""
    from app.models.api import BankAccountUpdate

    update = BankAccountUpdate()
    assert update.account_type is None
    assert update.currency is None
    assert update.is_active is None


# ---------------------------------------------------------------------------
# app.models.api — PaginatedResponse
# ---------------------------------------------------------------------------


def test_paginated_response_valid() -> None:
    """PaginatedResponse accepts a list payload."""
    from app.models.api import PaginatedResponse

    resp = PaginatedResponse(total=3, page=1, page_size=10, data=["a", "b", "c"])
    assert resp.total == 3
    assert len(resp.data) == 3


def test_paginated_response_page_size_bounds() -> None:
    """page_size must be between 1 and 100."""
    from app.models.api import PaginatedResponse

    with pytest.raises(ValidationError):
        PaginatedResponse(total=0, page=1, page_size=0, data=[])

    with pytest.raises(ValidationError):
        PaginatedResponse(total=0, page=1, page_size=101, data=[])


def test_paginated_response_page_ge_1() -> None:
    """page must be >= 1."""
    from app.models.api import PaginatedResponse

    with pytest.raises(ValidationError):
        PaginatedResponse(total=0, page=0, page_size=10, data=[])


# ---------------------------------------------------------------------------
# app.models.db — BankAccount
# ---------------------------------------------------------------------------


def test_bank_account_defaults() -> None:
    """BankAccount defaults: currency='EGP', is_active=True, last_synced_at=None."""
    from app.models.db import BankAccount

    account = BankAccount(
        id=uuid4(),
        user_id=uuid4(),
        bank_name="NBE",
        account_number_masked="****1234",
        account_type="savings",
        balance=Decimal("5000.00"),
        created_at=_now(),
        updated_at=_now(),
    )
    assert account.currency == "EGP"
    assert account.is_active is True
    assert account.last_synced_at is None


def test_bank_account_all_supported_banks() -> None:
    """BankAccount accepts all four supported bank names."""
    from app.models.db import BankAccount, SUPPORTED_BANKS

    for bank in SUPPORTED_BANKS:
        account = BankAccount(
            id=uuid4(),
            user_id=uuid4(),
            bank_name=bank,
            account_number_masked="****0000",
            account_type="current",
            balance=Decimal("0.00"),
            created_at=_now(),
            updated_at=_now(),
        )
        assert account.bank_name == bank


def test_bank_account_balance_decimal_precision() -> None:
    """Balance is stored as Decimal — no floating-point conversion."""
    from app.models.db import BankAccount

    account = BankAccount(
        id=uuid4(),
        user_id=uuid4(),
        bank_name="CIB",
        account_number_masked="****5678",
        account_type="current",
        balance=Decimal("12345.67"),
        created_at=_now(),
        updated_at=_now(),
    )
    assert account.balance == Decimal("12345.67")
    assert isinstance(account.balance, Decimal)


def test_bank_account_inactive_flag() -> None:
    """is_active can be explicitly set to False."""
    from app.models.db import BankAccount

    account = BankAccount(
        id=uuid4(),
        user_id=uuid4(),
        bank_name="BDC",
        account_number_masked="****0001",
        account_type="loan",
        balance=Decimal("0.00"),
        is_active=False,
        created_at=_now(),
        updated_at=_now(),
    )
    assert account.is_active is False


# ---------------------------------------------------------------------------
# app.models.db — Transaction
# ---------------------------------------------------------------------------


def test_transaction_defaults() -> None:
    """Transaction defaults: currency='EGP', is_categorized=False, optional fields None."""
    from app.models.db import Transaction

    txn = Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id="TXN-001",
        amount=Decimal("100.00"),
        transaction_type="debit",
        description="ATM Withdrawal",
        transaction_date=_today(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert txn.is_categorized is False
    assert txn.currency == "EGP"
    assert txn.category is None
    assert txn.sub_category is None
    assert txn.value_date is None
    assert txn.balance_after is None
    assert txn.raw_data == {}


def test_transaction_credit_type() -> None:
    """Transaction accepts 'credit' as transaction_type."""
    from app.models.db import Transaction

    txn = Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id="TXN-002",
        amount=Decimal("500.00"),
        transaction_type="credit",
        description="Salary deposit",
        transaction_date=_today(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert txn.transaction_type == "credit"


def test_transaction_with_category() -> None:
    """A categorized transaction stores category, sub_category, and flips is_categorized."""
    from app.models.db import Transaction

    txn = Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id="TXN-003",
        amount=Decimal("75.50"),
        transaction_type="debit",
        description="Supermarket purchase",
        transaction_date=_today(),
        category="Food & Dining",
        sub_category="Groceries",
        is_categorized=True,
        created_at=_now(),
        updated_at=_now(),
    )
    assert txn.is_categorized is True
    assert txn.category == "Food & Dining"
    assert txn.sub_category == "Groceries"


def test_transaction_amount_is_decimal() -> None:
    """Transaction amount is stored as Decimal, not float."""
    from app.models.db import Transaction

    txn = Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id="TXN-004",
        amount=Decimal("999.99"),
        transaction_type="debit",
        description="Online payment",
        transaction_date=_today(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert isinstance(txn.amount, Decimal)


def test_transaction_raw_data_stored() -> None:
    """raw_data dict is preserved as-is for audit purposes."""
    from app.models.db import Transaction

    raw = {"bank_ref": "ABC123", "channel": "ATM", "branch_code": "042"}
    txn = Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id="TXN-005",
        amount=Decimal("200.00"),
        transaction_type="debit",
        description="ATM",
        transaction_date=_today(),
        raw_data=raw,
        created_at=_now(),
        updated_at=_now(),
    )
    assert txn.raw_data == raw


# ---------------------------------------------------------------------------
# app.models.db — Loan
# ---------------------------------------------------------------------------


def test_loan_valid() -> None:
    """Loan model accepts a complete valid payload."""
    from app.models.db import Loan

    loan = Loan(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        loan_type="personal",
        principal_amount=Decimal("50000.00"),
        outstanding_balance=Decimal("45000.00"),
        interest_rate=Decimal("0.1850"),
        monthly_installment=Decimal("1500.00"),
        created_at=_now(),
        updated_at=_now(),
    )
    assert loan.loan_type == "personal"
    assert loan.next_payment_date is None
    assert loan.maturity_date is None


def test_loan_with_dates() -> None:
    """Loan model stores optional date fields correctly."""
    from app.models.db import Loan

    loan = Loan(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        loan_type="mortgage",
        principal_amount=Decimal("1000000.00"),
        outstanding_balance=Decimal("980000.00"),
        interest_rate=Decimal("0.1200"),
        monthly_installment=Decimal("12000.00"),
        next_payment_date=date(2026, 4, 1),
        maturity_date=date(2036, 4, 1),
        created_at=_now(),
        updated_at=_now(),
    )
    assert loan.next_payment_date == date(2026, 4, 1)
    assert loan.maturity_date == date(2036, 4, 1)


# ---------------------------------------------------------------------------
# app.models.db — Debt
# ---------------------------------------------------------------------------


def test_debt_defaults() -> None:
    """Debt status defaults to 'active', currency to 'EGP'."""
    from app.models.db import Debt

    debt = Debt(
        id=uuid4(),
        user_id=uuid4(),
        debt_type="lent",
        counterparty_name="Mariam",
        original_amount=Decimal("2000.00"),
        outstanding_balance=Decimal("2000.00"),
        created_at=_now(),
        updated_at=_now(),
    )
    assert debt.status == "active"
    assert debt.currency == "EGP"
    assert debt.due_date is None
    assert debt.notes is None
    assert debt.counterparty_phone is None
    assert debt.counterparty_email is None


def test_debt_partial_status() -> None:
    """Debt status can be explicitly set to 'partial'."""
    from app.models.db import Debt

    debt = Debt(
        id=uuid4(),
        user_id=uuid4(),
        debt_type="borrowed",
        counterparty_name="Omar",
        original_amount=Decimal("5000.00"),
        outstanding_balance=Decimal("2500.00"),
        status="partial",
        created_at=_now(),
        updated_at=_now(),
    )
    assert debt.status == "partial"
    assert debt.outstanding_balance == Decimal("2500.00")


# ---------------------------------------------------------------------------
# app.models.db — DebtPayment
# ---------------------------------------------------------------------------


def test_debt_payment_valid() -> None:
    """DebtPayment stores amount and payment_date correctly."""
    from app.models.db import DebtPayment

    payment = DebtPayment(
        id=uuid4(),
        debt_id=uuid4(),
        amount=Decimal("500.00"),
        payment_date=_today(),
        created_at=_now(),
    )
    assert payment.notes is None
    assert isinstance(payment.amount, Decimal)


def test_debt_payment_with_notes() -> None:
    """DebtPayment notes field is optional but stored when provided."""
    from app.models.db import DebtPayment

    payment = DebtPayment(
        id=uuid4(),
        debt_id=uuid4(),
        amount=Decimal("250.00"),
        payment_date=_today(),
        notes="Partial repayment via bank transfer",
        created_at=_now(),
    )
    assert payment.notes == "Partial repayment via bank transfer"


# ---------------------------------------------------------------------------
# app.models.db — UserProfile
# ---------------------------------------------------------------------------


def test_user_profile_valid() -> None:
    """UserProfile stores id and timestamps; full_name is optional."""
    from app.models.db import UserProfile

    profile = UserProfile(
        id=uuid4(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert profile.full_name is None


def test_user_profile_with_full_name() -> None:
    """full_name is stored when provided."""
    from app.models.db import UserProfile

    profile = UserProfile(
        id=uuid4(),
        full_name="Ahmed Hassan",
        created_at=_now(),
        updated_at=_now(),
    )
    assert profile.full_name == "Ahmed Hassan"
