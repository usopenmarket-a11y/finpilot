"""Pipeline runner — orchestrates the full ETL cycle.

Coordinates normalization, deduplication, and database persistence of
scraped bank data in a single idempotent operation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from supabase import AsyncClient

from app.models.db import Transaction
from app.pipeline.deduplicator import filter_new_transactions
from app.pipeline.normalizer import normalize
from app.pipeline.upserter import insert_transactions, upsert_account
from app.scrapers.base import ScraperResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    """Result of a successful pipeline run.

    Attributes:
        account_id: UUID of the bank account
        account_number_masked: Masked account number (last 4 digits)
        balance: Current account balance in the account's currency
        transactions_new: Number of transactions inserted
        transactions_skipped: Number of transactions deduplicated (already existed)
        ran_at: Timestamp when the pipeline completed
    """

    account_id: UUID
    account_number_masked: str
    balance: Decimal
    transactions_new: int
    transactions_skipped: int
    ran_at: datetime


async def run_pipeline(
    result: ScraperResult,
    user_id: UUID,
    supabase_client: AsyncClient,
) -> PipelineRunResult:
    """Execute the full ETL pipeline on a ScraperResult.

    Pipeline stages:
    1. Normalize: Transform raw scraper output into clean DB-ready records
    2. Upsert Account: Insert or update the bank account in the database
    3. Re-normalize Transactions: Update with the real account_id
    4. Deduplicate: Filter out transactions that already exist in the DB
    5. Insert Transactions: Bulk insert new transactions
    6. Summarize: Return metrics on the run

    The pipeline is idempotent: re-running with the same input produces
    the same database state.

    Args:
        result: ScraperResult from a bank scraper
        user_id: UUID of the user who scraped the account
        supabase_client: Supabase AsyncClient instance

    Returns:
        PipelineRunResult with metrics and summary

    Raises:
        Exception: On database errors (will be logged and propagated)
    """
    logger.info(
        "Pipeline started for user_id=%s bank=%s",
        user_id,
        result.account.bank_name,
    )

    # Stage 1: Normalize with a placeholder account_id
    # (we don't have the real account_id until we upsert)
    placeholder_account_id = UUID(int=0)
    normalized = normalize(result, user_id, placeholder_account_id)

    # Stage 2: Upsert account to get the real account_id
    real_account_id = await upsert_account(normalized.account, user_id, supabase_client)
    logger.info(
        "Account upserted: account_id=%s (user_id=%s)",
        real_account_id,
        user_id,
    )

    # Stage 3: Re-normalize transactions with the real account_id
    # (transactions from stage 1 have placeholder account_id)
    transactions_with_real_id = [
        Transaction(
            id=txn.id,
            user_id=txn.user_id,
            account_id=real_account_id,  # Update with real account_id
            external_id=txn.external_id,
            amount=txn.amount,
            currency=txn.currency,
            transaction_type=txn.transaction_type,
            description=txn.description,
            category=txn.category,
            sub_category=txn.sub_category,
            transaction_date=txn.transaction_date,
            value_date=txn.value_date,
            balance_after=txn.balance_after,
            raw_data=txn.raw_data,
            is_categorized=txn.is_categorized,
            created_at=txn.created_at,
            updated_at=txn.updated_at,
        )
        for txn in normalized.transactions
    ]

    # Stage 4: Deduplicate
    new_transactions = await filter_new_transactions(
        transactions_with_real_id, real_account_id, supabase_client
    )
    skipped_count = len(transactions_with_real_id) - len(new_transactions)
    logger.info(
        "Deduplication complete: %d new, %d skipped",
        len(new_transactions),
        skipped_count,
    )

    # Stage 5: Insert transactions
    inserted_count = 0
    if new_transactions:
        inserted_count = await insert_transactions(new_transactions, supabase_client)

    # Stage 6: Summarize
    now = datetime.now(UTC)
    result_obj = PipelineRunResult(
        account_id=real_account_id,
        account_number_masked=normalized.account.account_number_masked,
        balance=normalized.account.balance,
        transactions_new=inserted_count,
        transactions_skipped=skipped_count,
        ran_at=now,
    )

    logger.info(
        "Pipeline complete: account_id=%s txn_new=%d txn_skipped=%d",
        real_account_id,
        inserted_count,
        skipped_count,
    )

    return result_obj
