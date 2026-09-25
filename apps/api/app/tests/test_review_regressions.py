"""Regression coverage for account metadata, atomic ingestion, and persisted debt APIs."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.pipeline.normalizer import normalize_account
from app.pipeline.runner import run_pipeline
from app.pipeline.upserter import replace_credit_card_transactions, upsert_account
from app.routers import scrape, sync
from app.scrapers.base import ScraperParseError, ScraperResult
from app.scrapers.bdc_kony import BDCKonyScraper
from app.tests.test_pipeline import _make_bank_account, _make_transaction


async def test_scraped_metadata_and_credential_survive_normalize_and_upsert():
    user_id, credential_id = uuid4(), uuid4()
    account = _make_bank_account().model_copy(
        update={
            "account_type": "certificate",
            "opened_date": date(2026, 1, 15),
            "product_name": "Test certificate",
            "credential_label": "Personal",
            "credential_id": credential_id,
        }
    )
    normalized = normalize_account(account, user_id, uuid4())
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute = AsyncMock(
        return_value=SimpleNamespace(data=[{"id": str(uuid4())}])
    )
    await upsert_account(normalized, user_id, client)
    payload = client.table.return_value.upsert.call_args.args[0]
    assert payload["opened_date"] == "2026-01-15"
    assert payload["product_name"] == "Test certificate"
    assert payload["credential_id"] == str(credential_id)
    assert payload["credential_label"] == "Personal"


async def test_cc_pipeline_validates_before_replacing_history(monkeypatch):
    account = _make_bank_account().model_copy(update={"account_type": "credit_card"})
    monkeypatch.setattr("app.pipeline.runner.upsert_account", AsyncMock(return_value=account.id))
    replace = AsyncMock()
    monkeypatch.setattr("app.pipeline.runner.replace_credit_card_transactions", replace)
    monkeypatch.setattr(
        "app.pipeline.runner.normalize_transaction",
        MagicMock(side_effect=ValueError("invalid input")),
    )
    with pytest.raises(ValueError, match="invalid input"):
        await run_pipeline(
            ScraperResult(accounts=[account], transactions=[_make_transaction()]),
            uuid4(),
            MagicMock(),
        )
    replace.assert_not_awaited()


async def test_cc_pipeline_uses_atomic_rpc_instead_of_delete_insert(monkeypatch):
    account = _make_bank_account().model_copy(update={"account_type": "credit_card"})
    user_id = uuid4()
    client = MagicMock()
    client.rpc.return_value.execute = AsyncMock(return_value=SimpleNamespace(data=1))
    monkeypatch.setattr("app.pipeline.runner.upsert_account", AsyncMock(return_value=account.id))
    monkeypatch.setattr("app.pipeline.runner._categorize_and_update", AsyncMock(return_value=0))
    result = await run_pipeline(
        ScraperResult(accounts=[account], transactions=[_make_transaction()]), user_id, client
    )
    assert result.transactions_new == 1
    client.table.assert_not_called()
    name, payload = client.rpc.call_args.args
    assert name == "replace_credit_card_transactions"
    assert payload["p_transactions"][0]["account_id"] == str(account.id)
    assert payload["p_transactions"][0]["user_id"] == str(user_id)


async def test_cc_duplicate_rows_are_removed_before_rpc():
    user_id, account_id = uuid4(), uuid4()
    txn = _make_transaction(user_id=user_id, account_id=account_id)
    client = MagicMock()
    client.rpc.return_value.execute = AsyncMock(return_value=SimpleNamespace(data=1))
    assert await replace_credit_card_transactions(account_id, user_id, [txn, txn], client) == 1
    assert len(client.rpc.call_args.args[1]["p_transactions"]) == 1


async def test_direct_scrape_uses_async_database_client(monkeypatch):
    result = ScraperResult(accounts=[_make_bank_account()], transactions=[_make_transaction()])
    monkeypatch.setattr(scrape, "decrypt", lambda *_: "test-only")
    monkeypatch.setitem(
        scrape._SCRAPER_MAP,
        "NBE",
        MagicMock(return_value=SimpleNamespace(scrape=AsyncMock(return_value=result))),
    )
    client = MagicMock()
    async_factory = AsyncMock(return_value=client)
    monkeypatch.setattr(scrape, "get_async_service_role_client", async_factory)
    monkeypatch.setattr(scrape, "get_service_role_client", MagicMock())
    # Exercise the real pipeline with async query execution, so a sync-client
    # regression cannot be hidden by mocking run_pipeline itself.
    account_query, transaction_query = MagicMock(), MagicMock()
    account_query.upsert.return_value = account_query
    account_query.execute = AsyncMock(return_value=SimpleNamespace(data=[{"id": str(uuid4())}]))
    transaction_query.select.return_value = transaction_query
    transaction_query.eq.return_value = transaction_query
    transaction_query.upsert.return_value = transaction_query
    transaction_query.execute = AsyncMock(
        side_effect=[SimpleNamespace(data=[]), SimpleNamespace(data=[{}])]
    )
    client.table.side_effect = lambda table: (
        account_query if table == "bank_accounts" else transaction_query
    )
    monkeypatch.setattr("app.pipeline.runner._categorize_and_update", AsyncMock(return_value=0))
    response = await scrape.trigger_scrape(
        scrape.ScrapeRequest(bank="NBE", encrypted_username="test", encrypted_password="test"),
        uuid4(),
    )
    assert response.transactions_saved == 1
    async_factory.assert_awaited_once()


def test_sync_checks_bank_even_with_explicit_credential(monkeypatch):
    client, query = MagicMock(), MagicMock()
    client.table.return_value = query
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": str(uuid4())}])
    monkeypatch.setattr(sync, "get_service_role_client", lambda: client)
    sync._validate_credentials_exist(uuid4(), "NBE", str(uuid4()))
    assert ("bank", "NBE") in [call.args for call in query.eq.call_args_list]


async def test_invalid_bdc_date_rejects_batch_before_persistence(monkeypatch):
    from datetime import UTC, datetime

    scraper = BDCKonyScraper(username="test", password="test")
    monkeypatch.setattr(
        scraper,
        "_api_post",
        AsyncMock(
            return_value={
                "Transactions": [{"amount": "10", "transactionDate": "invalid"}],
            }
        ),
    )
    with pytest.raises(ScraperParseError, match="invalid date"):
        await scraper._fetch_card_transactions(
            MagicMock(), _make_bank_account(), {}, datetime.now(UTC)
        )
