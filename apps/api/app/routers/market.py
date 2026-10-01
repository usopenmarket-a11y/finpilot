"""Market overview router — prices, buy-window signals and data freshness.

Market rows are shared reference data (not per user), written only by the
market worker. Reading still requires a verified Supabase JWT.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from supabase._sync.client import Client

from app.deps import get_current_user_id, get_service_role_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])

STALE_AFTER = timedelta(minutes=30)
_SPARK_DAYS = 45


class MarketInstrument(BaseModel):
    symbol: str
    name: str
    asset_class: str
    unit: str
    quote_currency: str
    signals_enabled: bool
    price: Decimal | None = None
    as_of: datetime | None = None
    source: str | None = None
    change_1d: float | None = None
    change_30d: float | None = None
    sparkline: list[float] = Field(default_factory=list)
    history_days: int = 0


class MarketSignal(BaseModel):
    symbol: str
    name: str
    kind: str
    strength: str
    title: str
    detail: str
    stats: dict[str, Any]
    created_on: date
    expires_on: date


class MarketOverview(BaseModel):
    instruments: list[MarketInstrument]
    signals: list[MarketSignal]
    last_quotes_at: datetime | None
    stale: bool
    last_error: str | None


def _rows(data: Any) -> list[dict[str, Any]]:
    return [r for r in (data or []) if isinstance(r, dict)]


def _load(client: Client, today: date) -> MarketOverview:
    instruments = _rows(
        client.table("market_instruments").select("*").order("sort_order").execute().data
    )
    quotes = {
        r["symbol"]: r for r in _rows(client.table("market_quotes").select("*").execute().data)
    }
    since = (today - timedelta(days=_SPARK_DAYS)).isoformat()
    daily = _rows(
        client.table("market_daily")
        .select("symbol, day, close")
        .gte("day", since)
        .order("day")
        .limit(5000)
        .execute()
        .data
    )
    counts = {
        i["symbol"]: client.table("market_daily")
        .select("day", count="exact")  # type: ignore[arg-type]
        .eq("symbol", i["symbol"])
        .limit(1)
        .execute()
        .count
        or 0
        for i in instruments
    }
    closes: dict[str, list[tuple[date, float]]] = {}
    for r in daily:
        closes.setdefault(r["symbol"], []).append((date.fromisoformat(r["day"]), float(r["close"])))
    signals = _rows(
        client.table("market_signals")
        .select("*")
        .gte("expires_on", today.isoformat())
        .order("created_on", desc=True)
        .execute()
        .data
    )
    status_rows = _rows(client.table("market_worker_status").select("*").limit(1).execute().data)

    names = {i["symbol"]: i["name"] for i in instruments}
    out: list[MarketInstrument] = []
    for inst in instruments:
        symbol = inst["symbol"]
        series = closes.get(symbol, [])
        q = quotes.get(symbol)
        last = series[-1][1] if series else None
        prev = series[-2][1] if len(series) >= 2 else None
        month_ago = next((c for d, c in reversed(series) if d <= today - timedelta(days=30)), None)
        out.append(
            MarketInstrument(
                symbol=symbol,
                name=inst["name"],
                asset_class=inst["asset_class"],
                unit=inst["unit"],
                quote_currency=inst["quote_currency"],
                signals_enabled=bool(inst["signals_enabled"]),
                price=Decimal(str(q["price"])) if q else None,
                as_of=q["as_of"] if q else None,
                source=q["source"] if q else None,
                change_1d=(last / prev - 1) if last and prev else None,
                change_30d=(last / month_ago - 1) if last and month_ago else None,
                sparkline=[c for d, c in series if d >= today - timedelta(days=30)],
                history_days=counts.get(symbol, 0),
            )
        )

    # Keep the newest signal per (symbol, kind).
    seen: set[tuple[str, str]] = set()
    active: list[MarketSignal] = []
    for s in signals:
        key = (s["symbol"], s["kind"])
        if key in seen:
            continue
        seen.add(key)
        fields = {k: s[k] for k in MarketSignal.model_fields if k != "name"}
        active.append(MarketSignal(name=names.get(s["symbol"], s["symbol"]), **fields))

    worker = status_rows[0] if status_rows else {}
    last_quotes = worker.get("last_quotes_at")
    last_dt = datetime.fromisoformat(last_quotes) if isinstance(last_quotes, str) else None
    return MarketOverview(
        instruments=out,
        signals=active,
        last_quotes_at=last_dt,
        stale=last_dt is None or datetime.now(UTC) - last_dt > STALE_AFTER,
        last_error=worker.get("last_error"),
    )


@router.get(
    "/market/overview", response_model=MarketOverview, summary="Prices and buy-window signals"
)
async def market_overview(_user_id: object = Depends(get_current_user_id)) -> MarketOverview:
    try:
        return await asyncio.to_thread(_load, get_service_role_client(), date.today())
    except Exception as exc:
        logger.error("Market overview failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Market data unavailable"
        ) from exc
