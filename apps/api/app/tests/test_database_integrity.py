"""Actual PostgreSQL rollback, concurrency, and RLS tests.

Set FINPILOT_TEST_DATABASE_URL to an isolated localhost database named
finpilot_test. The fixture creates the legacy schema and applies the migration;
each test clears only this disposable database's fixture tables.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402 - optional integration dependency

_DSN = os.environ.get("FINPILOT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not _DSN, reason="Requires isolated PostgreSQL test database")


@pytest.fixture(scope="module")
def database():
    with psycopg.connect(_DSN, autocommit=True) as conn:
        assert conn.info.dbname == "finpilot_test"
        assert conn.info.host in {"localhost", "127.0.0.1", "::1"}
        if conn.execute("SELECT to_regclass('public.debts')").fetchone()[0] is None:
            conn.execute((Path(__file__).parent / "fixtures/legacy_ledger.sql").read_text())
            root = Path(__file__).resolve().parents[4]
            conn.execute((root / "supabase/migrations/20260907_fix_data_integrity.sql").read_text())
        yield conn


@pytest.fixture
def db(database):
    database.execute(
        "TRUNCATE public.debt_payments, public.debts, public.transactions, public.bank_accounts, public.bank_credentials CASCADE"
    )
    return database


def debt(db, amount=100):
    user_id, debt_id = uuid4(), uuid4()
    db.execute(
        "INSERT INTO debts(id, user_id, original_amount, outstanding_balance) VALUES (%s,%s,%s,%s)",
        (debt_id, user_id, amount, amount),
    )
    return user_id, debt_id


def pay(conn, debt_id, amount):
    return conn.execute(
        "INSERT INTO debt_payments(debt_id,amount,payment_date) VALUES (%s,%s,current_date) RETURNING id",
        (debt_id, amount),
    ).fetchone()[0]


def balance(db, debt_id):
    return db.execute(
        "SELECT outstanding_balance, status FROM debts WHERE id=%s", (debt_id,)
    ).fetchone()


def test_payment_insert_edit_delete_adjust_balance_atomically(db):
    _, debt_id = debt(db)
    payment_id = pay(db, debt_id, 30)
    assert balance(db, debt_id) == (70, "partial")
    db.execute("UPDATE debt_payments SET amount=100 WHERE id=%s", (payment_id,))
    assert balance(db, debt_id) == (0, "settled")
    db.execute("DELETE FROM debt_payments WHERE id=%s", (payment_id,))
    assert balance(db, debt_id) == (100, "active")


def test_payment_constraint_failure_rolls_back_balance_update(db):
    _, debt_id = debt(db)
    # BEFORE trigger executes, then the payment's NOT NULL constraint fails.
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            "INSERT INTO debt_payments(debt_id,amount,payment_date) VALUES (%s,30,NULL)", (debt_id,)
        )
    assert balance(db, debt_id) == (100, "active")
    assert db.execute("SELECT count(*) FROM debt_payments").fetchone()[0] == 0


@pytest.mark.parametrize("amount, expected, successes", [(30, 40, 2), (60, 40, 1)])
def test_concurrent_payments_serialize_and_reject_overpayment(db, amount, expected, successes):
    _, debt_id = debt(db)
    barrier = Barrier(2)

    def worker():
        with psycopg.connect(_DSN) as conn:
            barrier.wait(timeout=5)
            try:
                pay(conn, debt_id, amount)
                return True
            except psycopg.errors.CheckViolation:
                conn.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(results) == successes
    assert balance(db, debt_id)[0] == expected
    assert db.execute("SELECT count(*) FROM debt_payments").fetchone()[0] == successes


def test_original_amount_edit_uses_current_balance(db):
    _, debt_id = debt(db)
    pay(db, debt_id, 30)
    db.execute("UPDATE debts SET original_amount=120 WHERE id=%s", (debt_id,))
    assert balance(db, debt_id) == (90, "partial")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE debts SET original_amount=20 WHERE id=%s", (debt_id,))
    assert balance(db, debt_id) == (90, "partial")


def test_payment_rls_and_cascade(db):
    user_id, debt_id = debt(db)
    with db.transaction():
        db.execute("SET LOCAL ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(user_id),))
        pay(db, debt_id, 30)
        assert balance(db, debt_id) == (70, "partial")
    with pytest.raises(psycopg.Error):
        with db.transaction():
            db.execute("SET LOCAL ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(uuid4()),))
            pay(db, debt_id, 20)
    assert balance(db, debt_id) == (70, "partial")
    db.execute("DELETE FROM debts WHERE id=%s", (debt_id,))
    assert db.execute("SELECT count(*) FROM debt_payments").fetchone()[0] == 0


def card(db):
    user_id, account_id = uuid4(), uuid4()
    db.execute(
        "INSERT INTO bank_accounts(id,user_id,bank_name,account_type) VALUES (%s,%s,'NBE','credit_card')",
        (account_id, user_id),
    )
    return user_id, account_id


def transaction(user_id, account_id, reference, source="nbe_cc_statement", **overrides):
    return {
        "id": str(uuid4()),
        "user_id": str(user_id),
        "account_id": str(account_id),
        "external_id": reference,
        "amount": "10.00",
        "currency": "EGP",
        "transaction_type": "debit",
        "description": "Test purchase",
        "transaction_date": "2026-09-01",
        "raw_data": {"source": source},
        "is_categorized": False,
        **overrides,
    }


def replace(db, user_id, account_id, rows):
    return db.execute(
        "SELECT replace_credit_card_transactions(%s,%s,%s)", (account_id, user_id, Jsonb(rows))
    ).fetchone()[0]


def test_card_failed_replacement_retains_old_history(db):
    user_id, account_id = card(db)
    old = transaction(user_id, account_id, "old")
    replace(db, user_id, account_id, [old])
    with pytest.raises(psycopg.errors.CheckViolation):
        replace(db, user_id, account_id, [transaction(user_id, account_id, "bad", amount="-1")])
    assert db.execute("SELECT external_id FROM transactions").fetchall() == [("old",)]


def test_card_replacement_is_idempotent_and_preserves_missing_sections(db):
    user_id, account_id = card(db)
    replace(
        db,
        user_id,
        account_id,
        [
            transaction(user_id, account_id, "statement"),
            transaction(user_id, account_id, "unbilled", "nbe_cc_unbilled"),
        ],
    )
    new = transaction(user_id, account_id, "new-statement")
    assert replace(db, user_id, account_id, [new]) == 1
    assert replace(db, user_id, account_id, [new]) == 1
    assert db.execute("SELECT external_id FROM transactions ORDER BY external_id").fetchall() == [
        ("new-statement",),
        ("unbilled",),
    ]


def test_card_replacement_rejects_foreign_rows_and_authenticated_calls(db):
    user_id, account_id = card(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        replace(db, user_id, account_id, [transaction(uuid4(), account_id, "foreign")])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("SET LOCAL ROLE authenticated")
            replace(db, user_id, account_id, [transaction(user_id, account_id, "own")])


def test_deleting_one_credential_only_hides_its_accounts(db):
    user_id, first, second = uuid4(), uuid4(), uuid4()
    for cred in (first, second):
        db.execute(
            "INSERT INTO bank_credentials(id,user_id,bank) VALUES (%s,%s,'NBE')", (cred, user_id)
        )
        db.execute(
            "INSERT INTO bank_accounts(id,user_id,bank_name,account_type,credential_id) VALUES (%s,%s,'NBE','savings',%s)",
            (cred, user_id, cred),
        )
    db.execute("DELETE FROM bank_credentials WHERE id=%s", (first,))
    assert db.execute(
        "SELECT is_active,credential_id FROM bank_accounts WHERE id=%s", (first,)
    ).fetchone() == (False, None)
    assert db.execute(
        "SELECT is_active,credential_id FROM bank_accounts WHERE id=%s", (second,)
    ).fetchone() == (True, second)
