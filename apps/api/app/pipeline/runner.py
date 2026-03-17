"""Pipeline runner — orchestrates the full ETL cycle.

Coordinates normalization, deduplication, and database persistence of
scraped bank data in a single idempotent operation.

Multi-account support
---------------------
``ScraperResult`` now carries ``accounts: list[BankAccount]`` (one per
discovered bank account) and a flat ``transactions`` list whose entries each
carry ``raw_data["account_number_masked"]`` to identify their source account.

``run_pipeline`` processes each account independently:
1. Upsert the account to get its real ``account_id``.
2. Filter transactions belonging to that account using
   ``raw_data["account_number_masked"]``.
3. Deduplicate and insert those transactions.

The returned ``PipelineRunResult`` aggregates totals across all accounts and
reports the primary (first) account's ``account_id`` and masked number for
backward compatibility with the sync router.
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
from app.pipeline.normalizer import normalize_account, normalize_transaction
from app.pipeline.upserter import insert_transactions, upsert_account
from app.scrapers.base import ScraperResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    """Result of a successful pipeline run.

    For multi-account scrapes ``account_id`` and ``account_number_masked``
    report the *primary* (first) account.  ``transactions_new`` and
    ``transactions_skipped`` are aggregated across all accounts.

    Attributes:
        account_id: UUID of the primary bank account
        account_number_masked: Masked account number of the primary account
        balance: Current balance of the primary account
        transactions_new: Total transactions inserted (all accounts)
        transactions_skipped: Total transactions deduplicated (all accounts)
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

    Supports both single-account (legacy) and multi-account ScraperResults.
    Each account in ``result.accounts`` is upserted independently; transactions
    are routed to the correct account via ``raw_data["account_number_masked"]``.

    Pipeline stages (per account):
    1. Normalize account record
    2. Upsert account → get real account_id
    3. Filter transactions for this account by masked number
    4. Normalize those transactions with the real account_id
    5. Deduplicate against existing DB transactions
    6. Bulk insert new transactions

    The pipeline is idempotent: re-running with the same input produces
    the same database state.

    Args:
        result: ScraperResult from a bank scraper (may contain multiple accounts)
        user_id: UUID of the user who scraped the account
        supabase_client: Supabase AsyncClient instance

    Returns:
        PipelineRunResult with aggregate metrics and primary account info

    Raises:
        Exception: On database errors (will be logged and propagated)
    """
    bank_name = result.accounts[0].bank_name if result.accounts else "UNKNOWN"
    logger.info(
        "Pipeline started for user_id=%s bank=%s accounts=%d",
        user_id,
        bank_name,
        len(result.accounts),
    )

    total_inserted = 0
    total_skipped = 0
    primary_account_id: UUID = UUID(int=0)
    primary_masked: str = ""
    primary_balance: Decimal = Decimal("0.00")

    for acct_idx, raw_account in enumerate(result.accounts):
        # ------------------------------------------------------------------
        # Stage 1: Normalize account record
        # ------------------------------------------------------------------
        placeholder_account_id = UUID(int=0)
        normalized_account = normalize_account(raw_account, user_id, placeholder_account_id)

        # ------------------------------------------------------------------
        # Stage 2: Upsert account → real account_id
        # ------------------------------------------------------------------
        real_account_id = await upsert_account(normalized_account, user_id, supabase_client)
        logger.info(
            "Account upserted: idx=%d masked=%s account_id=%s",
            acct_idx,
            normalized_account.account_number_masked,
            real_account_id,
        )

        if acct_idx == 0:
            primary_account_id = real_account_id
            primary_masked = normalized_account.account_number_masked
            primary_balance = normalized_account.balance

        # ------------------------------------------------------------------
        # Stage 3: Filter transactions belonging to this account
        # ------------------------------------------------------------------
        account_masked = normalized_account.account_number_masked
        account_txns = [
            txn
            for txn in result.transactions
            if txn.raw_data.get("account_number_masked") == account_masked
        ]

        # Fallback: if no transaction carries account_number_masked routing
        # (e.g. from an older single-account scrape) and this is the only
        # account, treat all transactions as belonging to it.
        if not account_txns and len(result.accounts) == 1:
            account_txns = list(result.transactions)

        logger.info(
            "Account idx=%d masked=%s — %d transaction(s) to process",
            acct_idx,
            account_masked,
            len(account_txns),
        )

        if not account_txns:
            continue

        # ------------------------------------------------------------------
        # Stage 4: Normalize transactions with the real account_id
        # ------------------------------------------------------------------
        normalized_txns = [
            _rebuild_transaction_with_real_id(
                normalize_transaction(txn, user_id, placeholder_account_id),
                real_account_id,
            )
            for txn in account_txns
        ]

        # ------------------------------------------------------------------
        # Stage 5: Deduplicate
        # ------------------------------------------------------------------
        new_transactions = await filter_new_transactions(
            normalized_txns, real_account_id, supabase_client
        )
        skipped = len(normalized_txns) - len(new_transactions)
        logger.info(
            "Dedup idx=%d masked=%s: %d new, %d skipped",
            acct_idx,
            account_masked,
            len(new_transactions),
            skipped,
        )
        total_skipped += skipped

        # ------------------------------------------------------------------
        # Stage 6: Insert
        # ------------------------------------------------------------------
        if new_transactions:
            inserted = await insert_transactions(new_transactions, supabase_client)
            total_inserted += inserted

    now = datetime.now(UTC)
    logger.info(
        "Pipeline complete: primary_account_id=%s txn_new=%d txn_skipped=%d",
        primary_account_id,
        total_inserted,
        total_skipped,
    )

    return PipelineRunResult(
        account_id=primary_account_id,
        account_number_masked=primary_masked,
        balance=primary_balance,
        transactions_new=total_inserted,
        transactions_skipped=total_skipped,
        ran_at=now,
    )


def _rebuild_transaction_with_real_id(txn: Transaction, real_account_id: UUID) -> Transaction:
    """Return a copy of ``txn`` with ``account_id`` replaced by ``real_account_id``."""
    return Transaction(
        id=txn.id,
        user_id=txn.user_id,
        account_id=real_account_id,
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
