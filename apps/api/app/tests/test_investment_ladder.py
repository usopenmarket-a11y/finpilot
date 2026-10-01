"""Tests for the personal investment ladder engine and its router helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.recommendations.investment_ladder import (
    AccountSnapshot,
    AssetSnapshot,
    Assumptions,
    PlanInputs,
    TransactionSnapshot,
    build_investment_plan,
    estimate_monthly_flows,
)
from app.routers.investment import _assumptions_from, _hidden_card_ids

TODAY = date(2026, 10, 1)
SYNCED = datetime(2026, 10, 1, 8, tzinfo=UTC)


def _account(**kw: object) -> AccountSnapshot:
    base: dict[str, object] = {
        "id": "a1",
        "bank": "NBE",
        "account_type": "savings",
        "masked": "****0010",
        "balance": Decimal("0"),
        "last_synced_at": SYNCED,
    }
    base.update(kw)
    return AccountSnapshot(**base)  # type: ignore[arg-type]


def _txn(account_id: str, amount: str, kind: str, day: date, category: str | None = None):
    return TransactionSnapshot(
        account_id=account_id,
        amount=Decimal(amount),
        transaction_type=kind,  # type: ignore[arg-type]
        category=category,
        transaction_date=day,
    )


def _spending(account_id: str, monthly: str) -> list[TransactionSnapshot]:
    """One debit per each of the 3 full months before TODAY."""
    return [_txn(account_id, monthly, "debit", date(2026, m, 15)) for m in (7, 8, 9)]


def _plan(accounts, transactions=(), **kw):
    inputs = PlanInputs(accounts=list(accounts), transactions=list(transactions), **kw)
    return build_investment_plan(inputs, kw.pop("assumptions", Assumptions()), TODAY)


def _step(plan, key):
    return next(s for s in plan.steps if s.key == key)


# ---------------------------------------------------------------------------
# Spending estimate
# ---------------------------------------------------------------------------


def test_spending_excludes_transfers_and_counts_card_purchases() -> None:
    savings = _account(id="s")
    card = _account(id="c", account_type="credit_card")
    txns = [
        *_spending("c", "6000"),  # card purchases
        *[_txn("s", "1000", "debit", date(2026, m, 3)) for m in (7, 8, 9)],  # cash spending
        *[_txn("s", "6000", "debit", date(2026, m, 5), "Transfers") for m in (7, 8, 9)],
        *[_txn("s", "20000", "credit", date(2026, m, 1), "Income") for m in (7, 8, 9)],
        _txn("s", "999999", "debit", date(2026, 10, 1)),  # current month ignored
    ]
    spend, income, months = estimate_monthly_flows([savings, card], txns, TODAY)
    assert (spend, income, months) == (Decimal("7000"), Decimal("20000"), 3)


def test_no_transactions_gives_info_not_bad_advice() -> None:
    plan = _plan([_account(balance=Decimal("100"))])
    assert _step(plan, "starter_buffer").status == "info"
    assert _step(plan, "full_buffer").status == "info"


# ---------------------------------------------------------------------------
# Ladder steps
# ---------------------------------------------------------------------------


def test_starter_buffer_gap_when_cash_below_one_month() -> None:
    plan = _plan([_account(balance=Decimal("2000"))], _spending("a1", "5000"))
    step = _step(plan, "starter_buffer")
    assert step.status == "action"
    assert step.cards[0].amount_egp == Decimal("3000")


def test_card_asks_only_for_what_is_still_owed_and_flags_overdue() -> None:
    card = _account(
        id="c",
        account_type="credit_card",
        masked="****6046",
        balance=Decimal("108180"),
        billed_amount=Decimal("117603"),
        minimum_payment=Decimal("8275"),
        payment_due_date=date(2026, 9, 27),
        last_synced_at=datetime(2026, 9, 26, tzinfo=UTC),
    )
    plan = _plan([_account(balance=Decimal("50000")), card], _spending("a1", "1000"))
    rec = _step(plan, "cards").cards[0]
    assert rec.amount_egp == Decimal("108180")
    assert rec.priority == "urgent"
    assert "overdue since 27 Sep" in rec.why
    assert "already paid EGP 9,423" in rec.why
    assert "sync to confirm" in rec.why  # data older than two days
    # (108180 - 8275) * 3% a month
    assert rec.impact_monthly_egp == Decimal("2997")
    assert plan.next_best_action is not None and plan.next_best_action.id == rec.id


def test_card_paid_after_statement_needs_no_action() -> None:
    card = _account(
        id="c", account_type="credit_card", balance=Decimal("0"), billed_amount=Decimal("5000")
    )
    plan = _plan([card])
    assert _step(plan, "cards").status == "done"


def test_overdraft_costing_more_than_certificate_is_flagged() -> None:
    cert = _account(
        id="cert",
        account_type="certificate",
        masked="****0025",
        balance=Decimal("1400000"),
        interest_rate=Decimal("0.215"),
        maturity_date=date(2027, 5, 20),
    )
    overdraft = _account(
        id="od",
        account_type="loan",
        masked="****0015",
        balance=Decimal("38936"),
        product_name="جاري مدين بضمان اوعية ادخارية -افراد",
    )
    plan = _plan([cert, overdraft])
    rec = _step(plan, "costly_debt").cards[0]
    assert rec.confidence == "low"  # estimated rate
    assert "certificate rate + 2 points" in rec.why
    assert "matures May 2027" in rec.why
    assert rec.impact_monthly_egp == Decimal("65")  # 38936 * 2% / 12

    # A user-supplied rate replaces the estimate and raises confidence.
    a = Assumptions(loan_rates={"od": Decimal("0.20")}, user_set=["loan_rates"])
    inputs = PlanInputs(accounts=[cert, overdraft])
    plan = build_investment_plan(inputs, a, TODAY)
    assert _step(plan, "costly_debt").status == "info"  # 20% < 21.5%


def test_unknown_loan_rate_asks_user_and_informal_debt_is_mentioned() -> None:
    loan = _account(id="l", account_type="loan", masked="****3218", balance=Decimal("659679"))
    plan = _plan([loan], borrowed_debts_egp=Decimal("270000"))
    step = _step(plan, "costly_debt")
    assert [c.id for c in step.cards] == ["loan-rate-missing"]
    assert "EGP 270,000 to people" in step.summary


def test_market_gate_opens_only_when_foundations_are_done() -> None:
    rich = _account(balance=Decimal("100000"))
    cert = _account(
        id="cert",
        account_type="certificate",
        balance=Decimal("50000"),
        interest_rate=Decimal("0.2"),
    )
    plan = _plan([rich, cert], _spending("a1", "10000"))
    assert plan.market_gate_open is True
    assert _step(plan, "market").status == "info"
    assert _step(plan, "mix").cards  # idle cash suggestion appears once open

    card = _account(
        id="c", account_type="credit_card", balance=Decimal("500"), billed_amount=Decimal("500")
    )
    plan = _plan([rich, cert, card], _spending("a1", "10000"))
    assert plan.market_gate_open is False
    assert _step(plan, "market").status == "locked"


def test_holdings_compute_real_return_and_wait_for_prices() -> None:
    cert = _account(
        id="cert", account_type="certificate", balance=Decimal("100"), interest_rate=Decimal("0.2")
    )
    usd = _account(id="usd", currency="USD", balance=Decimal("50"))
    plan = _plan(
        [cert, usd],
        assets=[AssetSnapshot(asset_type="gold", name="Ring", quantity=Decimal("5"), unit="grams")],
    )
    by_key = {h.key: h for h in plan.holdings}
    assert by_key["egp_certificates"].real_return_annual == Decimal("0.05")
    assert by_key["egp_cash"].real_return_annual == Decimal("-0.15")
    assert by_key["foreign_currency"].value_egp is None
    assert "USD 50" in by_key["foreign_currency"].detail
    assert "5 grams Ring" in by_key["gold"].detail


# ---------------------------------------------------------------------------
# Router helpers
# ---------------------------------------------------------------------------


def test_stored_assumptions_mark_user_set_and_reject_bad_values() -> None:
    a = _assumptions_from({"investment_assumptions": {"card_monthly_rate": "0.025"}})
    assert a.card_monthly_rate == Decimal("0.025")
    assert a.user_set == ["card_monthly_rate"]
    assert _assumptions_from({"investment_assumptions": {"inflation_annual": "5"}}) == Assumptions()


def test_hidden_cards_respect_snooze_expiry() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    prefs = {
        "investment_feedback": {
            "done": {"action": "done", "until": None},
            "snoozed": {"action": "snooze", "until": (now + timedelta(days=3)).isoformat()},
            "expired": {"action": "snooze", "until": (now - timedelta(days=1)).isoformat()},
        }
    }
    assert _hidden_card_ids(prefs, now) == {"done", "snoozed"}


# ---------------------------------------------------------------------------
# HTTP endpoints (data access stubbed; auth is the real JWT check)
# ---------------------------------------------------------------------------


class _FakeTable:
    """Records upserts and returns canned rows for selects."""

    def __init__(self, store: dict[str, object], name: str) -> None:
        self.store, self.name = store, name

    def __getattr__(self, _attr: str):  # select/eq/limit/... chain
        return lambda *_a, **_k: self

    def upsert(self, row: dict[str, object], **_k: object) -> _FakeTable:
        self.store["prefs"] = row["preferences"]
        return self

    def execute(self):
        from types import SimpleNamespace

        if self.name == "user_profiles":
            return SimpleNamespace(data=[{"preferences": self.store.get("prefs", {})}])
        if self.name == "bank_accounts":
            return SimpleNamespace(data=[{"id": "own-loan"}])
        return SimpleNamespace(data=[])


async def test_feedback_hides_card_and_assumptions_only_keep_own_loans(
    client, auth_headers, monkeypatch
) -> None:
    import app.routers.investment as inv

    store: dict[str, object] = {}

    class FakeClient:
        def table(self, name: str) -> _FakeTable:
            return _FakeTable(store, name)

    card = _account(
        id="c",
        account_type="credit_card",
        balance=Decimal("500"),
        billed_amount=Decimal("500"),
        payment_due_date=date.today() + timedelta(days=20),
    )

    def fake_load(_client, _uid, _today):
        return PlanInputs(accounts=[card]), dict(store.get("prefs", {}))  # type: ignore[arg-type]

    monkeypatch.setattr(inv, "get_service_role_client", FakeClient)
    monkeypatch.setattr(inv, "_load_inputs", fake_load)
    headers = auth_headers()

    resp = await client.get("/api/v1/recommendations/investment-plan", headers=headers)
    assert resp.status_code == 200
    card_id = resp.json()["next_best_action"]["id"]

    resp = await client.post(
        "/api/v1/recommendations/investment-plan/feedback",
        headers=headers,
        json={"card_id": card_id, "action": "done"},
    )
    assert resp.status_code == 204
    plan = (await client.get("/api/v1/recommendations/investment-plan", headers=headers)).json()
    assert plan["next_best_action"] is None
    assert all(c["id"] != card_id for s in plan["steps"] for c in s["cards"])

    resp = await client.put(
        "/api/v1/recommendations/investment-plan/assumptions",
        headers=headers,
        json={"card_monthly_rate": 0.025, "loan_rates": {"own-loan": 0.2, "someone-else": 0.1}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["loan_rates"] == {"own-loan": "0.2"}
    assert sorted(body["user_set"]) == ["card_monthly_rate", "loan_rates"]

    bad = await client.put(
        "/api/v1/recommendations/investment-plan/assumptions",
        headers=headers,
        json={"card_monthly_rate": 0.5},
    )
    assert bad.status_code == 422


async def test_investment_plan_requires_auth(client) -> None:
    resp = await client.get("/api/v1/recommendations/investment-plan")
    assert resp.status_code in (401, 403)
