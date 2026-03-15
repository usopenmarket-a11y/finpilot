"""Deduplication stage of the ETL pipeline.

Prevents double-inserts by checking the database for existing transactions
with the same (account_id, external_id) pair. Uses a single SELECT query
to fetch all existing external_ids for an account, then filters the input
transactions to return only new ones.
"""

from __future__ import annotations

import logging
from uuid import UUID

from supabase import AsyncClient

from app.models.db import Transaction

logger = logging.getLogger(__name__)


async def filter_new_transactions(
    transactions: list[Transaction],
    account_id: UUID,
    supabase_client: AsyncClient,
) -> list[Transaction]:
    """Filter transactions to return only those not already in the database.

    Fetches the set of external_ids already associated with the account from
    Supabase in a single SELECT query, then filters the input list to return
    only transactions whose external_id is NOT already in the DB.

    Args:
        transactions: List of normalized Transaction objects to filter
        account_id: UUID of the bank account
        supabase_client: Supabase AsyncClient instance

    Returns:
        List of transactions whose external_id is not yet in the database

    Raises:
        Exception: If the database query fails (will be caught and logged by caller)
    """
    if not transactions:
        return []

    # Fetch all external_ids for this account
    existing_external_ids = await _fetch_existing_external_ids(
        account_id, supabase_client
    )

    # Filter to only new transactions
    new_transactions = [
        txn
        for txn in transactions
        if txn.external_id not in existing_external_ids
    ]

    # Log deduplication stats
    skipped_count = len(transactions) - len(new_transactions)
    if skipped_count > 0:
        logger.info(
            "Deduplication: %d/%d transactions already exist (account_id=%s)",
            skipped_count,
            len(transactions),
            account_id,
        )

    return new_transactions


async def _fetch_existing_external_ids(
    account_id: UUID,
    supabase_client: AsyncClient,
) -> set[str]:
    """Fetch all external_ids for an account from the database.

    Args:
        account_id: UUID of the bank account
        supabase_client: Supabase AsyncClient instance

    Returns:
        Set of external_id strings that already exist for this account

    Raises:
        Exception: If the query fails
    """
    response = await supabase_client.table("transactions").select(
        "external_id"
    ).eq("account_id", str(account_id)).execute()

    # Extract external_ids from the response
    external_ids: set[str] = set()
    if response.data:
        for row in response.data:
            if isinstance(row, dict) and "external_id" in row:
                external_ids.add(row["external_id"])

    logger.debug(
        "Fetched %d existing external_ids for account_id=%s",
        len(external_ids),
        account_id,
    )

    return external_ids
