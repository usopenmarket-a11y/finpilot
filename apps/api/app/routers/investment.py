"""Personal investment ladder router.

Unlike the stateless recommendation endpoints, these read the caller's own
synced data. Every query filters by ``user_id`` taken from the verified
Supabase JWT (``app.deps.get_current_user_id``); nothing is client-supplied.

Assumptions and card feedback are stored on ``user_profiles.preferences``
under ``investment_assumptions`` and ``investment_feedback``.

Logs carry counts only — never balances, names, or account numbers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from supabase._sync.client import Client

from app.deps import get_current_user_id, get_service_role_client
from app.recommendations.investment_ladder import (
    AccountSnapshot,
    AssetSnapshot,
    Assumptions,
    InvestmentPlan,
    PlanInputs,
    TransactionSnapshot,
    build_investment_plan,
    next_best_action,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])

_ASSUMPTIONS_KEY = "investment_assumptions"
_FEEDBACK_KEY = "investment_feedback"
_LOOKBACK_DAYS = 120


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1, max_length=200)
    action: Literal["done", "snooze", "dismiss"]
    snooze_days: int = Field(default=7, ge=1, le=90)


class AssumptionsRequest(BaseModel):
    """Editable assumptions; omitted fields keep their current value."""

    model_config = ConfigDict(extra="forbid")

    card_monthly_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.10"))
    inflation_annual: Decimal | None = Field(default=None, ge=0, le=Decimal("1"))
    emergency_months: int | None = Field(default=None, ge=1, le=12)
    loan_rates: dict[str, Decimal] | None = None


def _rows(data: Any) -> list[dict[str, Any]]:
    """Keep only object rows from a Supabase response."""
    return [r for r in (data or []) if isinstance(r, dict)]


def _read_preferences(client: Client, user_id: UUID) -> dict[str, Any]:
    rows = _rows(
        client.table("user_profiles")
        .select("preferences")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
        .data
    )
    prefs = rows[0].get("preferences") if rows else None
    return prefs if isinstance(prefs, dict) else {}


def _write_preferences(client: Client, user_id: UUID, prefs: dict[str, Any]) -> None:
    client.table("user_profiles").upsert(
        {"id": str(user_id), "preferences": prefs, "updated_at": datetime.now(UTC).isoformat()},
        on_conflict="id",
    ).execute()


def _assumptions_from(prefs: dict[str, Any]) -> Assumptions:
    stored = prefs.get(_ASSUMPTIONS_KEY)
    if not isinstance(stored, dict):
        return Assumptions()
    try:
        return Assumptions(**stored, user_set=sorted(k for k in stored if k != "user_set"))
    except (ValidationError, TypeError):
        logger.warning("Ignoring invalid stored investment assumptions")
        return Assumptions()


def _load_inputs(client: Client, user_id: UUID, today: date) -> tuple[PlanInputs, dict[str, Any]]:
    uid = str(user_id)
    accounts = _rows(
        client.table("bank_accounts")
        .select("*")
        .eq("user_id", uid)
        .eq("is_active", True)
        .execute()
        .data
    )
    since = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    txns = _rows(
        client.table("transactions")
        .select("account_id, amount, transaction_type, category, transaction_date")
        .eq("user_id", uid)
        .gte("transaction_date", since)
        .limit(10000)
        .execute()
        .data
    )
    debts = _rows(
        client.table("debts")
        .select("outstanding_balance, currency")
        .eq("user_id", uid)
        .eq("debt_type", "borrowed")
        .in_("status", ["active", "partial"])
        .execute()
        .data
    )
    installments = _rows(
        client.table("installments")
        .select("monthly_amount")
        .eq("user_id", uid)
        .eq("is_active", True)
        .execute()
        .data
    )
    assets = _rows(
        client.table("assets")
        .select(
            "asset_type, name, quantity, unit, currency_code, current_value_egp, purchase_price_egp"
        )
        .eq("user_id", uid)
        .execute()
        .data
    )
    prefs = _read_preferences(client, user_id)
    prices, change_1y, signals_active = _load_market(client, today)

    snapshots = [
        AccountSnapshot(
            id=str(a["id"]),
            bank=a.get("bank_name") or "",
            account_type=a.get("account_type") or "",
            masked=a.get("account_number_masked") or "",
            currency=a.get("currency") or "EGP",
            balance=Decimal(str(a.get("balance") or 0)),
            credit_limit=a.get("credit_limit"),
            billed_amount=a.get("billed_amount"),
            minimum_payment=a.get("minimum_payment"),
            payment_due_date=a.get("payment_due_date"),
            interest_rate=a.get("interest_rate"),
            maturity_date=a.get("maturity_date"),
            product_name=a.get("product_name"),
            last_synced_at=a.get("last_synced_at"),
        )
        for a in accounts
    ]
    synced = [str(a["last_synced_at"]) for a in accounts if a.get("last_synced_at")]
    inputs = PlanInputs(
        accounts=snapshots,
        transactions=[
            TransactionSnapshot(**t)
            for t in txns
            if t.get("transaction_type") in ("debit", "credit")
        ],
        borrowed_debts_egp=sum(
            (
                Decimal(str(d.get("outstanding_balance") or 0))
                for d in debts
                if (d.get("currency") or "EGP") == "EGP"
            ),
            Decimal("0"),
        ),
        installments_monthly_egp=sum(
            (Decimal(str(i.get("monthly_amount") or 0)) for i in installments), Decimal("0")
        ),
        assets=[
            AssetSnapshot(
                asset_type=str(s.get("asset_type") or "other"),
                name=s.get("name") or "",
                quantity=s.get("quantity"),
                unit=s.get("unit"),
                currency_code=s.get("currency_code"),
                value_egp=s.get("current_value_egp") or s.get("purchase_price_egp"),
            )
            for s in assets
        ],
        data_as_of=datetime.fromisoformat(max(synced)) if synced else None,
        prices=prices,
        price_change_1y=change_1y,
        market_signals_active=signals_active,
    )
    return inputs, prefs


_VALUATION_SYMBOLS = ("USDEGP", "EUREGP", "GOLD21_EGP", "SILVER_EGP")


def _load_market(client: Client, today: date) -> tuple[dict[str, Decimal], dict[str, Decimal], int]:
    """Latest EGP prices, their 12-month change, and active buy-signal count.

    Market data is optional: any failure leaves holdings unvalued instead of
    failing the plan.
    """
    try:
        quotes = _rows(
            client.table("market_quotes")
            .select("symbol, price")
            .in_("symbol", list(_VALUATION_SYMBOLS))
            .execute()
            .data
        )
        prices = {q["symbol"]: Decimal(str(q["price"])) for q in quotes}
        year_ago = (today - timedelta(days=365)).isoformat()
        change: dict[str, Decimal] = {}
        for symbol, price in prices.items():
            past = _rows(
                client.table("market_daily")
                .select("close")
                .eq("symbol", symbol)
                .lte("day", year_ago)
                .order("day", desc=True)
                .limit(1)
                .execute()
                .data
            )
            if past:
                change[symbol] = price / Decimal(str(past[0]["close"])) - 1
        enabled = {
            r["symbol"]
            for r in _rows(
                client.table("market_instruments")
                .select("symbol")
                .eq("signals_enabled", True)
                .execute()
                .data
            )
        }
        signals = _rows(
            client.table("market_signals")
            .select("symbol")
            .gte("expires_on", today.isoformat())
            .execute()
            .data
        )
        active = len({s["symbol"] for s in signals if s["symbol"] in enabled})
        return prices, change, active
    except Exception as exc:
        logger.warning("Market data unavailable for plan: %s", type(exc).__name__)
        return {}, {}, 0


def _hidden_card_ids(prefs: dict[str, Any], now: datetime) -> set[str]:
    feedback = prefs.get(_FEEDBACK_KEY)
    if not isinstance(feedback, dict):
        return set()
    hidden: set[str] = set()
    for card_id, entry in feedback.items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("until")
        if until is None:
            hidden.add(card_id)  # done / dismissed
            continue
        try:
            if datetime.fromisoformat(until) > now:
                hidden.add(card_id)
        except (TypeError, ValueError):
            continue
    return hidden


@router.get(
    "/recommendations/investment-plan",
    response_model=InvestmentPlan,
    summary="Personal investment ladder from the caller's own data",
)
async def get_investment_plan(user_id: UUID = Depends(get_current_user_id)) -> InvestmentPlan:
    today = date.today()
    client = get_service_role_client()
    try:
        inputs, prefs = await asyncio.to_thread(_load_inputs, client, user_id, today)
    except Exception as exc:
        logger.error("Investment plan data load failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to load your data"
        ) from exc

    plan = build_investment_plan(inputs, _assumptions_from(prefs), today)
    hidden = _hidden_card_ids(prefs, datetime.now(UTC))
    if hidden:
        for step in plan.steps:
            step.cards = [c for c in step.cards if c.id not in hidden]
        plan.next_best_action = next_best_action(plan.steps)
    logger.info(
        "Investment plan built",
        extra={"accounts": len(inputs.accounts), "cards": sum(len(s.cards) for s in plan.steps)},
    )
    return plan


@router.post(
    "/recommendations/investment-plan/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a recommendation done, snoozed, or dismissed",
)
async def post_feedback(
    body: FeedbackRequest, user_id: UUID = Depends(get_current_user_id)
) -> None:
    client = get_service_role_client()

    def _apply() -> None:
        prefs = _read_preferences(client, user_id)
        feedback = prefs.get(_FEEDBACK_KEY)
        feedback = dict(feedback) if isinstance(feedback, dict) else {}
        until = (
            (datetime.now(UTC) + timedelta(days=body.snooze_days)).isoformat()
            if body.action == "snooze"
            else None
        )
        feedback[body.card_id] = {
            "action": body.action,
            "until": until,
            "at": datetime.now(UTC).isoformat(),
        }
        _write_preferences(client, user_id, {**prefs, _FEEDBACK_KEY: feedback})

    try:
        await asyncio.to_thread(_apply)
    except Exception as exc:
        logger.error("Investment feedback save failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save feedback"
        ) from exc


@router.put(
    "/recommendations/investment-plan/assumptions",
    response_model=Assumptions,
    summary="Update the rates used by the investment ladder",
)
async def put_assumptions(
    body: AssumptionsRequest, user_id: UUID = Depends(get_current_user_id)
) -> Assumptions:
    if body.loan_rates is not None and any(
        not (Decimal("0") <= r <= Decimal("1")) for r in body.loan_rates.values()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Loan rates must be between 0 and 1"
        )
    client = get_service_role_client()

    def _apply() -> Assumptions:
        prefs = _read_preferences(client, user_id)
        stored = prefs.get(_ASSUMPTIONS_KEY)
        stored = dict(stored) if isinstance(stored, dict) else {}
        if body.loan_rates is not None:
            # Only keep rates for the caller's own active loan accounts.
            own = {
                str(r["id"])
                for r in _rows(
                    client.table("bank_accounts")
                    .select("id")
                    .eq("user_id", str(user_id))
                    .eq("account_type", "loan")
                    .execute()
                    .data
                )
            }
            stored["loan_rates"] = {
                k: str(v)
                for k, v in {**stored.get("loan_rates", {}), **body.loan_rates}.items()
                if k in own
            }
        for key in ("card_monthly_rate", "inflation_annual", "emergency_months"):
            value = getattr(body, key)
            if value is not None:
                stored[key] = str(value) if isinstance(value, Decimal) else value
        _write_preferences(client, user_id, {**prefs, _ASSUMPTIONS_KEY: stored})
        return _assumptions_from({_ASSUMPTIONS_KEY: stored})

    try:
        return await asyncio.to_thread(_apply)
    except Exception as exc:
        logger.error("Investment assumptions save failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save assumptions"
        ) from exc
