"""Normalization stage of the ETL pipeline.

Transforms raw ScraperResult into clean, DB-ready BankAccount and Transaction
objects. Handles currency normalization, type standardization, whitespace
stripping, and other data hygiene tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.models.db import BankAccount, Transaction
from app.scrapers.base import ScraperResult


@dataclass
class NormalizedResult:
    """Container for normalized account and transaction data.

    Attributes:
        account: Fully populated BankAccount (id, user_id, created_at, updated_at
                 are set by the upserter layer)
        transactions: List of normalized Transaction objects ready for insertion
    """

    account: BankAccount
    transactions: list[Transaction]


def normalize(
    result: ScraperResult,
    user_id: UUID,
    account_id: UUID,
) -> NormalizedResult:
    """Normalize a ScraperResult into clean, DB-ready records.

    Transformations applied:
    - Fills user_id and account_id on account and all transactions
    - Normalizes currency codes to ISO 4217 uppercase (e.g. 'egp' → 'EGP')
    - Normalizes transaction_type to lowercase ('Debit' → 'debit')
    - Strips whitespace from description
    - Ensures amount is always positive Decimal
    - Sets is_categorized=False on all transactions
    - Sets account.last_synced_at = datetime.now(timezone.utc)

    Args:
        result: Raw ScraperResult from the scraper layer
        user_id: UUID of the user who owns this account
        account_id: UUID of the bank account (may be a placeholder before DB insert)

    Returns:
        NormalizedResult containing clean account and transaction objects

    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Normalize the primary account (first in list for backward compat)
    normalized_account = normalize_account(result.account, user_id, account_id)

    # Normalize transactions
    normalized_transactions = [
        normalize_transaction(txn, user_id, account_id) for txn in result.transactions
    ]

    return NormalizedResult(
        account=normalized_account,
        transactions=normalized_transactions,
    )


def normalize_account(
    account: BankAccount,
    user_id: UUID,
    account_id: UUID,
) -> BankAccount:
    """Normalize a single BankAccount record.

    Public alias for ``_normalize_account`` — consumed directly by the
    multi-account pipeline runner.

    Args:
        account: Raw account from scraper
        user_id: User ID to assign
        account_id: Account ID to assign

    Returns:
        Normalized BankAccount
    """
    return _normalize_account(account, user_id, account_id)


def normalize_transaction(
    txn: Transaction,
    user_id: UUID,
    account_id: UUID,
) -> Transaction:
    """Normalize a single Transaction record.

    Public alias for ``_normalize_transaction`` — consumed directly by the
    multi-account pipeline runner.

    Args:
        txn: Raw transaction from scraper
        user_id: User ID to assign
        account_id: Account ID to assign

    Returns:
        Normalized Transaction
    """
    return _normalize_transaction(txn, user_id, account_id)


def _normalize_account(
    account: BankAccount,
    user_id: UUID,
    account_id: UUID,
) -> BankAccount:
    """Normalize a single BankAccount record.

    Args:
        account: Raw account from scraper
        user_id: User ID to assign
        account_id: Account ID to assign

    Returns:
        Normalized BankAccount
    """
    return BankAccount(
        id=account_id,
        user_id=user_id,
        bank_name=account.bank_name.upper(),
        account_number_masked=account.account_number_masked.strip(),
        account_type=account.account_type.lower().strip(),
        currency=(account.currency or "EGP").upper().strip(),
        balance=account.balance if account.balance >= 0 else account.balance,
        is_active=account.is_active,
        last_synced_at=datetime.now(UTC),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _normalize_transaction(
    txn: Transaction,
    user_id: UUID,
    account_id: UUID,
) -> Transaction:
    """Normalize a single Transaction record.

    Args:
        txn: Raw transaction from scraper
        user_id: User ID to assign
        account_id: Account ID to assign

    Returns:
        Normalized Transaction
    """
    return Transaction(
        id=txn.id,
        user_id=user_id,
        account_id=account_id,
        external_id=txn.external_id.strip(),
        amount=abs(txn.amount),  # Ensure always positive
        currency=(txn.currency or "EGP").upper().strip(),
        transaction_type=txn.transaction_type.lower().strip(),
        description=txn.description.strip(),
        category=None,
        sub_category=None,
        transaction_date=txn.transaction_date,
        value_date=txn.value_date,
        balance_after=txn.balance_after,
        raw_data=txn.raw_data or {},
        is_categorized=False,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
    )
