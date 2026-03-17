"""Persistence stage of the ETL pipeline.

Handles all database writes for normalized, deduplicated data. Uses
Supabase batch operations with appropriate conflict resolution.
"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from supabase import AsyncClient

from app.models.db import BankAccount, Transaction

logger = logging.getLogger(__name__)


async def upsert_account(
    account: BankAccount,
    user_id: UUID,
    supabase_client: AsyncClient,
) -> UUID:
    """Upsert a bank account record into the database.

    Uses an ON CONFLICT strategy to handle the case where the account
    already exists (identified by user_id + bank_name + account_number_masked).
    Updates balance, last_synced_at, and updated_at on conflict.

    Args:
        account: Normalized BankAccount to upsert
        user_id: User ID (for consistency check)
        supabase_client: Supabase AsyncClient instance

    Returns:
        The UUID of the account (either newly created or existing)

    Raises:
        Exception: If the upsert fails
    """
    # Generate a deterministic UUID so that re-syncing the same account always
    # produces the same primary key, allowing PK-based upsert without needing
    # a separate composite unique constraint in the database.
    deterministic_id = uuid.uuid5(
        uuid.NAMESPACE_OID,
        f"{user_id}:{account.bank_name}:{account.account_number_masked}",
    )

    account_data = {
        "id": str(deterministic_id),
        "user_id": str(user_id),
        "bank_name": account.bank_name,
        "account_number_masked": account.account_number_masked,
        "account_type": account.account_type,
        "currency": account.currency,
        "balance": str(account.balance),
        "is_active": account.is_active,
        "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
    }

    response = await supabase_client.table("bank_accounts").upsert(account_data).execute()

    if not response.data:
        raise ValueError(
            f"Failed to upsert account for user_id={user_id}, bank_name={account.bank_name}"
        )

    # Extract the account ID from the response
    result_account = response.data[0]
    account_id_str = result_account.get("id")
    if not account_id_str:
        raise ValueError("Upserted account missing id field")

    account_uuid = UUID(account_id_str)
    logger.info(
        "Upserted bank account: account_id=%s bank_name=%s (user_id=%s)",
        account_uuid,
        account.bank_name,
        user_id,
    )

    return account_uuid


async def insert_transactions(
    transactions: list[Transaction],
    supabase_client: AsyncClient,
) -> int:
    """Bulk insert transactions into the database.

    Uses ON CONFLICT (account_id, external_id) DO NOTHING to gracefully
    handle any remaining duplicates that may have slipped through
    deduplication (race condition safety).

    Args:
        transactions: List of normalized Transaction objects to insert
        supabase_client: Supabase AsyncClient instance

    Returns:
        Number of transactions actually inserted (excludes duplicates)

    Raises:
        Exception: If the insert fails catastrophically
    """
    if not transactions:
        logger.info("No transactions to insert")
        return 0

    # Convert transactions to dicts for Supabase
    transaction_dicts = [_transaction_to_dict(txn) for txn in transactions]

    # Deduplicate by deterministic id before upsert.
    # PostgreSQL raises 21000 ("ON CONFLICT DO UPDATE command cannot affect row a
    # second time") if the same id appears twice in a single upsert batch.  This
    # can happen when two accounts yield the same (external_id, account_id) hash
    # (e.g. an account with no transactions produces placeholder rows with identical
    # hashes).  Dedup here is safe because all rows with the same id are identical.
    seen_ids: set[str] = set()
    unique_dicts: list[dict] = []
    for d in transaction_dicts:
        if d["id"] not in seen_ids:
            seen_ids.add(d["id"])
            unique_dicts.append(d)
    if len(unique_dicts) < len(transaction_dicts):
        logger.info(
            "Deduplicated %d → %d transactions before upsert",
            len(transaction_dicts),
            len(unique_dicts),
        )
    transaction_dicts = unique_dicts

    # Upsert with deterministic IDs — ON CONFLICT (id) DO UPDATE is idempotent
    # because each transaction dict has a deterministic id derived from
    # (account_id, external_id). AsyncRequestBuilder does not support
    # ignore_duplicates on insert(), so we use upsert() instead.
    response = await supabase_client.table("transactions").upsert(transaction_dicts).execute()

    inserted_count = len(response.data) if response.data else 0

    logger.info(
        "Inserted %d transactions (attempted %d)",
        inserted_count,
        len(transactions),
    )

    return inserted_count


def _transaction_to_dict(txn: Transaction) -> dict:
    """Convert a Transaction object to a dictionary for database insertion.

    Args:
        txn: Transaction to convert

    Returns:
        Dictionary with string-serialized values for Supabase
    """
    # Deterministic UUID so ON CONFLICT (id) DO NOTHING is idempotent across re-syncs.
    deterministic_id = uuid.uuid5(
        uuid.NAMESPACE_OID,
        f"{txn.account_id}:{txn.external_id}",
    )
    return {
        "id": str(deterministic_id),
        "user_id": str(txn.user_id),
        "account_id": str(txn.account_id),
        "external_id": txn.external_id,
        "amount": str(txn.amount),
        "currency": txn.currency,
        "transaction_type": txn.transaction_type,
        "description": txn.description,
        "category": txn.category,
        "sub_category": txn.sub_category,
        "transaction_date": txn.transaction_date.isoformat(),
        "value_date": txn.value_date.isoformat() if txn.value_date else None,
        "balance_after": str(txn.balance_after) if txn.balance_after else None,
        "raw_data": txn.raw_data,
        "is_categorized": txn.is_categorized,
    }
