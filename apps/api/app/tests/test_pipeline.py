"""Unit tests for the M3 ETL pipeline.

Covers:
- normalizer.normalize()           — data hygiene and field assignment
- deduplicator.filter_new_transactions() — duplicate detection via external_id
- upserter.upsert_account()        — Supabase upsert call and UUID extraction
- upserter.insert_transactions()   — Supabase batch insert and row count
- runner.run_pipeline()            — end-to-end orchestration and result shape

All Supabase interactions are intercepted by AsyncMock — no real DB connections.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.db import BankAccount, Transaction
from app.pipeline.deduplicator import filter_new_transactions
from app.pipeline.normalizer import NormalizedResult, normalize
from app.pipeline.runner import PipelineRunResult, run_pipeline
from app.pipeline.upserter import insert_transactions, upsert_account
from app.scrapers.base import ScraperResult

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=UTC)
_TODAY = date.today()


def _make_bank_account(bank_name: str = "NBE") -> BankAccount:
    """Return a minimal valid BankAccount with sensible defaults."""
    return BankAccount(
        id=uuid4(),
        user_id=uuid4(),
        bank_name=bank_name,
        account_number_masked="****1234",
        account_type="savings",
        currency="EGP",
        balance=Decimal("10000.00"),
        is_active=True,
        last_synced_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_transaction(
    account_id: UUID | None = None,
    user_id: UUID | None = None,
    external_id: str = "TXN-001",
    amount: Decimal = Decimal("250.00"),
    currency: str = "EGP",
    transaction_type: str = "debit",
    description: str = "ATM Withdrawal",
) -> Transaction:
    """Return a minimal valid Transaction."""
    return Transaction(
        id=uuid4(),
        user_id=user_id or uuid4(),
        account_id=account_id or uuid4(),
        external_id=external_id,
        amount=amount,
        currency=currency,
        transaction_type=transaction_type,
        description=description,
        transaction_date=_TODAY,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_scraper_result(bank_name: str = "NBE", n_transactions: int = 3) -> ScraperResult:
    """Factory fixture: build a ScraperResult with n_transactions unique entries."""
    account = _make_bank_account(bank_name)
    transactions = [
        _make_transaction(
            account_id=account.id,
            user_id=account.user_id,
            external_id=f"TXN-{i:04d}",
            description=f"Transaction {i}",
        )
        for i in range(n_transactions)
    ]
    return ScraperResult(accounts=[account], transactions=transactions)


def mock_supabase_client() -> AsyncMock:
    """Return a fully-stubbed AsyncMock that mimics supabase.AsyncClient.

    The table() call returns a fluent builder whose terminal .execute() is an
    AsyncMock that callers can override per test.
    """
    client = AsyncMock()

    # Default table builder: select/upsert/insert all return a builder with
    # an execute() coroutine that returns an empty success response.
    def _make_builder() -> AsyncMock:
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = []
        execute_result.count = 0
        builder.execute = AsyncMock(return_value=execute_result)
        # Chain methods back to the same builder so .select().eq() etc. work.
        builder.select = MagicMock(return_value=builder)
        builder.eq = MagicMock(return_value=builder)
        builder.upsert = MagicMock(return_value=builder)
        builder.insert = MagicMock(return_value=builder)
        return builder

    client.table = MagicMock(side_effect=lambda _name: _make_builder())
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def scraper_result_3() -> ScraperResult:
    return make_scraper_result("NBE", n_transactions=3)


@pytest.fixture
def scraper_result_empty() -> ScraperResult:
    return make_scraper_result("CIB", n_transactions=0)


@pytest.fixture
def supabase() -> AsyncMock:
    return mock_supabase_client()


# ===========================================================================
# Normalizer tests
# ===========================================================================


class TestNormalizer:
    """Tests for app.pipeline.normalizer.normalize()."""

    def test_normalize_sets_user_id_and_account_id(self, scraper_result_3: ScraperResult) -> None:
        """normalize() stamps user_id and account_id onto every transaction."""
        uid = uuid4()
        aid = uuid4()
        result = normalize(scraper_result_3, uid, aid)

        assert result.account.user_id == uid
        assert result.account.id == aid
        for txn in result.transactions:
            assert txn.user_id == uid
            assert txn.account_id == aid

    def test_normalize_currency_uppercased(self, user_id: UUID, account_id: UUID) -> None:
        """normalize() converts lowercase currency codes to ISO 4217 uppercase."""
        raw_account = _make_bank_account("NBE")
        # Manually override currency to lowercase to simulate raw scraper output.
        raw_account = raw_account.model_copy(update={"currency": "egp"})
        raw_txn = _make_transaction(currency="egp")
        scraper_result = ScraperResult(accounts=[raw_account], transactions=[raw_txn])

        result = normalize(scraper_result, user_id, account_id)

        assert result.account.currency == "EGP"
        assert result.transactions[0].currency == "EGP"

    def test_normalize_transaction_type_lowercased(self, user_id: UUID, account_id: UUID) -> None:
        """normalize() converts transaction_type to lowercase."""
        raw_txn = _make_transaction(transaction_type="Debit")
        scraper_result = ScraperResult(accounts=[_make_bank_account("NBE")], transactions=[raw_txn])

        result = normalize(scraper_result, user_id, account_id)

        assert result.transactions[0].transaction_type == "debit"

    def test_normalize_strips_description_whitespace(self, user_id: UUID, account_id: UUID) -> None:
        """normalize() strips leading/trailing whitespace from description."""
        raw_txn = _make_transaction(description="  ATM Withdrawal  ")
        scraper_result = ScraperResult(accounts=[_make_bank_account("NBE")], transactions=[raw_txn])

        result = normalize(scraper_result, user_id, account_id)

        assert result.transactions[0].description == "ATM Withdrawal"

    def test_normalize_amount_is_positive_decimal(self, user_id: UUID, account_id: UUID) -> None:
        """normalize() ensures amount is always a positive Decimal (abs applied)."""
        raw_txn = _make_transaction(amount=Decimal("-350.75"))
        scraper_result = ScraperResult(accounts=[_make_bank_account("NBE")], transactions=[raw_txn])

        result = normalize(scraper_result, user_id, account_id)

        assert result.transactions[0].amount == Decimal("350.75")
        assert result.transactions[0].amount > 0
        assert isinstance(result.transactions[0].amount, Decimal)

    def test_normalize_sets_is_categorized_false(self, user_id: UUID, account_id: UUID) -> None:
        """normalize() forces is_categorized=False on all transactions."""
        # Construct a transaction that claims to be categorized already.
        raw_txn = _make_transaction()
        raw_txn = raw_txn.model_copy(update={"is_categorized": True, "category": "Food"})
        scraper_result = ScraperResult(accounts=[_make_bank_account("NBE")], transactions=[raw_txn])

        result = normalize(scraper_result, user_id, account_id)

        assert result.transactions[0].is_categorized is False

    def test_normalize_sets_last_synced_at(
        self, scraper_result_3: ScraperResult, user_id: UUID, account_id: UUID
    ) -> None:
        """normalize() sets account.last_synced_at to a recent UTC datetime."""
        before = datetime.now(tz=UTC)
        result = normalize(scraper_result_3, user_id, account_id)
        after = datetime.now(tz=UTC)

        synced = result.account.last_synced_at
        assert synced is not None
        assert synced.tzinfo is not None  # timezone-aware
        assert before <= synced <= after

    def test_normalize_zero_transactions_returns_empty_list(
        self, scraper_result_empty: ScraperResult, user_id: UUID, account_id: UUID
    ) -> None:
        """normalize() with a ScraperResult that has no transactions returns []."""
        result = normalize(scraper_result_empty, user_id, account_id)

        assert isinstance(result, NormalizedResult)
        assert result.transactions == []


# ===========================================================================
# Deduplicator tests
# ===========================================================================


class TestDeduplicator:
    """Tests for app.pipeline.deduplicator.filter_new_transactions()."""

    async def test_all_transactions_new_when_db_empty(
        self, account_id: UUID, supabase: AsyncMock
    ) -> None:
        """Returns all transactions when the DB has no existing external_ids."""
        transactions = [_make_transaction(external_id=f"TXN-{i:04d}") for i in range(4)]

        # Stub DB returning empty data (no existing rows).
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = []
        builder.execute = AsyncMock(return_value=execute_result)
        builder.select = MagicMock(return_value=builder)
        builder.eq = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        result = await filter_new_transactions(transactions, account_id, supabase)

        assert len(result) == 4
        assert result == transactions

    async def test_existing_transactions_are_filtered_out(
        self, account_id: UUID, supabase: AsyncMock
    ) -> None:
        """Transactions whose external_id already exists in DB are excluded."""
        transactions = [
            _make_transaction(external_id="TXN-EXISTING"),
            _make_transaction(external_id="TXN-NEW-001"),
            _make_transaction(external_id="TXN-NEW-002"),
        ]

        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [{"external_id": "TXN-EXISTING"}]
        builder.execute = AsyncMock(return_value=execute_result)
        builder.select = MagicMock(return_value=builder)
        builder.eq = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        result = await filter_new_transactions(transactions, account_id, supabase)

        assert len(result) == 2
        result_ids = {t.external_id for t in result}
        assert "TXN-EXISTING" not in result_ids
        assert "TXN-NEW-001" in result_ids
        assert "TXN-NEW-002" in result_ids

    async def test_returns_empty_when_all_already_exist(
        self, account_id: UUID, supabase: AsyncMock
    ) -> None:
        """Returns [] when every transaction is already in the DB."""
        transactions = [
            _make_transaction(external_id="TXN-A"),
            _make_transaction(external_id="TXN-B"),
        ]

        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [
            {"external_id": "TXN-A"},
            {"external_id": "TXN-B"},
        ]
        builder.execute = AsyncMock(return_value=execute_result)
        builder.select = MagicMock(return_value=builder)
        builder.eq = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        result = await filter_new_transactions(transactions, account_id, supabase)

        assert result == []

    async def test_empty_input_returns_empty_list_no_db_call(
        self, account_id: UUID, supabase: AsyncMock
    ) -> None:
        """filter_new_transactions([]) short-circuits and never calls Supabase."""
        result = await filter_new_transactions([], account_id, supabase)

        assert result == []
        supabase.table.assert_not_called()


# ===========================================================================
# Upserter tests
# ===========================================================================


class TestUpserter:
    """Tests for app.pipeline.upserter.upsert_account() and insert_transactions()."""

    async def test_upsert_account_calls_correct_table(self, user_id: UUID) -> None:
        """upsert_account() targets the 'bank_accounts' table."""
        account = _make_bank_account("NBE")
        returned_uuid = uuid4()

        supabase = AsyncMock()
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [{"id": str(returned_uuid)}]
        builder.execute = AsyncMock(return_value=execute_result)
        builder.upsert = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        await upsert_account(account, user_id, supabase)

        supabase.table.assert_called_once_with("bank_accounts")

    async def test_upsert_account_returns_uuid(self, user_id: UUID) -> None:
        """upsert_account() returns the UUID from the response data."""
        account = _make_bank_account("CIB")
        expected_uuid = uuid4()

        supabase = AsyncMock()
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [{"id": str(expected_uuid)}]
        builder.execute = AsyncMock(return_value=execute_result)
        builder.upsert = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        result = await upsert_account(account, user_id, supabase)

        assert result == expected_uuid
        assert isinstance(result, UUID)

    async def test_insert_transactions_calls_correct_table(self) -> None:
        """insert_transactions() targets the 'transactions' table."""
        transactions = [_make_transaction(external_id="TXN-001")]

        supabase = AsyncMock()
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [{}]
        execute_result.count = 1
        builder.execute = AsyncMock(return_value=execute_result)
        builder.upsert = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        await insert_transactions(transactions, supabase)

        supabase.table.assert_called_once_with("transactions")

    async def test_insert_transactions_returns_correct_count(self) -> None:
        """insert_transactions() returns the count from the Supabase response."""
        transactions = [_make_transaction(external_id=f"TXN-{i:03d}") for i in range(5)]

        supabase = AsyncMock()
        builder = MagicMock()
        execute_result = MagicMock()
        execute_result.data = [{} for _ in range(5)]
        execute_result.count = 5
        builder.execute = AsyncMock(return_value=execute_result)
        builder.upsert = MagicMock(return_value=builder)
        supabase.table = MagicMock(return_value=builder)

        inserted = await insert_transactions(transactions, supabase)

        assert inserted == 5

    async def test_insert_transactions_empty_list_returns_zero(self) -> None:
        """insert_transactions([]) returns 0 without touching Supabase."""
        supabase = AsyncMock()

        inserted = await insert_transactions([], supabase)

        assert inserted == 0
        supabase.table.assert_not_called()


# ===========================================================================
# Runner tests
# ===========================================================================


class TestRunner:
    """Tests for app.pipeline.runner.run_pipeline()."""

    def _make_pipeline_supabase(
        self,
        *,
        account_uuid: UUID,
        existing_external_ids: list[str] | None = None,
        insert_count: int | None = None,
    ) -> AsyncMock:
        """Build a Supabase mock pre-configured for a full pipeline run.

        Configures two distinct table() call targets:
        - 'bank_accounts' upsert returns account_uuid
        - 'transactions' select returns existing_external_ids (for dedup)
        - 'transactions' insert returns insert_count

        The runner calls table("transactions") twice — once for the SELECT
        deduplication query and once for the INSERT.  The call counter lives
        outside the per-builder closure so it is shared across both invocations
        of the same table name.
        """
        if existing_external_ids is None:
            existing_external_ids = []

        supabase = AsyncMock()

        # Shared counter for "transactions" table calls, keyed outside the
        # per-call factory so it persists across multiple table() invocations.
        txn_call_counter: dict[str, int] = {"n": 0}

        def _table_factory(table_name: str) -> MagicMock:
            builder = MagicMock()

            if table_name == "bank_accounts":
                execute_result = MagicMock()
                execute_result.data = [{"id": str(account_uuid)}]
                builder.execute = AsyncMock(return_value=execute_result)
                builder.upsert = MagicMock(return_value=builder)

            elif table_name == "transactions":
                # Capture which call number this builder represents at the
                # moment it is created — call 1 is the SELECT, call 2 is INSERT.
                txn_call_counter["n"] += 1
                this_call = txn_call_counter["n"]

                if this_call == 1:
                    # Deduplication SELECT response
                    execute_result = MagicMock()
                    execute_result.data = [{"external_id": eid} for eid in existing_external_ids]
                    builder.execute = AsyncMock(return_value=execute_result)
                    builder.select = MagicMock(return_value=builder)
                    builder.eq = MagicMock(return_value=builder)
                else:
                    # UPSERT response (insert_transactions uses upsert)
                    n_inserted = insert_count if insert_count is not None else 0
                    execute_result = MagicMock()
                    execute_result.data = [{}] * n_inserted
                    execute_result.count = n_inserted
                    builder.execute = AsyncMock(return_value=execute_result)
                    builder.upsert = MagicMock(return_value=builder)
            else:
                execute_result = MagicMock()
                execute_result.data = []
                execute_result.count = 0
                builder.execute = AsyncMock(return_value=execute_result)

            return builder

        supabase.table = MagicMock(side_effect=_table_factory)
        return supabase

    async def test_run_pipeline_happy_path(self) -> None:
        """run_pipeline() happy path returns a valid PipelineRunResult."""
        uid = uuid4()
        real_account_uuid = uuid4()
        scraper_result = make_scraper_result("NBE", n_transactions=3)

        supabase = self._make_pipeline_supabase(
            account_uuid=real_account_uuid,
            existing_external_ids=[],
            insert_count=3,
        )

        before = datetime.now(tz=UTC)
        result = await run_pipeline(scraper_result, uid, supabase)
        after = datetime.now(tz=UTC)

        assert isinstance(result, PipelineRunResult)
        assert result.account_id == real_account_uuid
        assert isinstance(result.account_number_masked, str)
        assert isinstance(result.balance, Decimal)
        assert result.transactions_new == 3
        assert result.transactions_skipped == 0
        assert before <= result.ran_at <= after

    async def test_run_pipeline_new_plus_skipped_equals_total_scraped(self) -> None:
        """transactions_new + transactions_skipped == len(scraper_result.transactions)."""
        uid = uuid4()
        real_account_uuid = uuid4()
        n_total = 6
        n_existing = 2
        n_new = n_total - n_existing

        scraper_result = make_scraper_result("CIB", n_transactions=n_total)
        existing_ids = [scraper_result.transactions[i].external_id for i in range(n_existing)]

        supabase = self._make_pipeline_supabase(
            account_uuid=real_account_uuid,
            existing_external_ids=existing_ids,
            insert_count=n_new,
        )

        result = await run_pipeline(scraper_result, uid, supabase)

        assert result.transactions_new + result.transactions_skipped == n_total
        assert result.transactions_skipped == n_existing
        assert result.transactions_new == n_new

    async def test_run_pipeline_all_deduped_gives_zero_new(self) -> None:
        """When all transactions are duplicates, transactions_new == 0."""
        uid = uuid4()
        real_account_uuid = uuid4()
        scraper_result = make_scraper_result("BDC", n_transactions=4)
        all_ids = [t.external_id for t in scraper_result.transactions]

        supabase = self._make_pipeline_supabase(
            account_uuid=real_account_uuid,
            existing_external_ids=all_ids,
            insert_count=0,
        )

        result = await run_pipeline(scraper_result, uid, supabase)

        assert result.transactions_new == 0
        assert result.transactions_skipped == 4

    def test_pipeline_run_result_has_required_fields(self) -> None:
        """PipelineRunResult dataclass exposes all documented fields."""
        now = datetime.now(tz=UTC)
        pipeline_result = PipelineRunResult(
            account_id=uuid4(),
            account_number_masked="****9999",
            balance=Decimal("5000.00"),
            transactions_new=10,
            transactions_skipped=2,
            ran_at=now,
        )

        assert hasattr(pipeline_result, "account_id")
        assert hasattr(pipeline_result, "account_number_masked")
        assert hasattr(pipeline_result, "balance")
        assert hasattr(pipeline_result, "transactions_new")
        assert hasattr(pipeline_result, "transactions_skipped")
        assert hasattr(pipeline_result, "ran_at")

        assert isinstance(pipeline_result.account_id, UUID)
        assert isinstance(pipeline_result.transactions_new, int)
        assert isinstance(pipeline_result.transactions_skipped, int)
        assert isinstance(pipeline_result.ran_at, datetime)
