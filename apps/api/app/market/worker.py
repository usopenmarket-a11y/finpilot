"""24/7 market worker: ``python -m app.market.worker``.

Runs in its own container next to the API. Every ``QUOTE_INTERVAL_S`` it
refreshes the latest price of each instrument (falling back to a second free
source when Yahoo fails), updates today's close, and recomputes buy-window
signals. About once a day it reloads two years of daily history. A heartbeat
row (``market_worker_status``) lets the app show data freshness.

Failures are isolated per instrument and per stage; the loop never exits on a
data error. SIGTERM/SIGINT stop it cleanly between steps.
"""

from __future__ import annotations

import logging
import random
import signal
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.deps import get_service_role_client
from app.market import sources
from app.market.analysis import build_signals
from app.market.catalog import (
    GOLD_USD_OZ,
    INSTRUMENTS,
    SILVER_USD_OZ,
    USD_EGP,
    gold21_per_gram,
    silver_per_gram,
)

logger = logging.getLogger("app.market.worker")

QUOTE_INTERVAL_S = 600
HISTORY_MAX_AGE = timedelta(hours=20)
HISTORY_DAYS = 520
_PAUSE_S = 1.0  # between upstream calls, to stay polite to free sources
STATUS_ID = "market-worker"
# Touched after every cycle; the container health check reads its age.
HEARTBEAT_FILE = Path("/tmp/market-worker.heartbeat")

_stop = False


def _request_stop(*_args: object) -> None:
    global _stop
    _stop = True
    logger.info("Stop requested; finishing current step")


def _chunks(rows: list[dict[str, Any]], size: int = 500) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def upsert_instruments(db: Any) -> None:
    db.table("market_instruments").upsert(
        [
            {
                "symbol": i.symbol,
                "name": i.name,
                "asset_class": i.asset_class,
                "unit": i.unit,
                "quote_currency": i.quote_currency,
                "signals_enabled": i.signals_enabled,
                "sort_order": i.sort_order,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            for i in INSTRUMENTS
        ],
        on_conflict="symbol",
    ).execute()


def save_daily(db: Any, symbol: str, closes: list[tuple[date, Decimal]]) -> None:
    rows = [{"symbol": symbol, "day": d.isoformat(), "close": str(c)} for d, c in closes]
    for chunk in _chunks(rows):
        db.table("market_daily").upsert(chunk, on_conflict="symbol,day").execute()


def save_quote(db: Any, symbol: str, price: Decimal, as_of: datetime, source: str) -> None:
    db.table("market_quotes").upsert(
        {"symbol": symbol, "price": str(price), "as_of": as_of.isoformat(), "source": source},
        on_conflict="symbol",
    ).execute()
    save_daily(db, symbol, [(as_of.date(), price)])


def load_closes(db: Any, symbol: str) -> list[tuple[date, Decimal]]:
    rows = (
        db.table("market_daily")
        .select("day, close")
        .eq("symbol", symbol)
        .gte("day", (date.today() - timedelta(days=HISTORY_DAYS * 2)).isoformat())
        .order("day")
        .limit(2000)
        .execute()
        .data
    )
    return [(date.fromisoformat(r["day"]), Decimal(str(r["close"]))) for r in rows or []]


def heartbeat(db: Any, **fields: Any) -> None:
    db.table("market_worker_status").upsert(
        {"id": STATUS_ID, "updated_at": datetime.now(UTC).isoformat(), **fields},
        on_conflict="id",
    ).execute()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def derive_per_gram(
    metal: list[tuple[date, Decimal]],
    fx: list[tuple[date, Decimal]],
    convert: Any,
) -> list[tuple[date, Decimal]]:
    """Combine a USD/oz series with USD/EGP, carrying the last FX rate forward."""
    fx_sorted = sorted(fx)
    out: list[tuple[date, Decimal]] = []
    j, rate = 0, None
    for day, usd in sorted(metal):
        while j < len(fx_sorted) and fx_sorted[j][0] <= day:
            rate = fx_sorted[j][1]
            j += 1
        if rate is not None:
            out.append((day, convert(usd, rate)))
    return out


def refresh_history(db: Any, http: httpx.Client) -> list[str]:
    """Reload ~2 years of daily closes. Returns symbols that failed."""
    failed: list[str] = []
    series: dict[str, list[tuple[date, Decimal]]] = {}
    for ticker in (USD_EGP, GOLD_USD_OZ, SILVER_USD_OZ):
        try:
            series[ticker] = sources.yahoo_chart(http, ticker)[0]
        except sources.SourceError as exc:
            logger.warning("History for %s failed: %s", ticker, exc)
        time.sleep(_PAUSE_S)
    for inst in INSTRUMENTS:
        if _stop:
            break
        try:
            if inst.yahoo is not None:
                closes = (
                    series[USD_EGP]
                    if inst.yahoo == USD_EGP and USD_EGP in series
                    else sources.yahoo_chart(http, inst.yahoo)[0]
                )
                time.sleep(_PAUSE_S)
            else:
                metal = GOLD_USD_OZ if inst.symbol == "GOLD21_EGP" else SILVER_USD_OZ
                convert = gold21_per_gram if inst.symbol == "GOLD21_EGP" else silver_per_gram
                if metal not in series or USD_EGP not in series:
                    raise sources.SourceError("inputs unavailable")
                closes = derive_per_gram(series[metal], series[USD_EGP], convert)
            if not closes:
                raise sources.SourceError("no closes")
            save_daily(db, inst.symbol, closes)
        except sources.SourceError as exc:
            logger.warning("History for %s failed: %s", inst.symbol, exc)
            failed.append(inst.symbol)
    return failed


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


def _fallback_quote(http: httpx.Client, fallback: str) -> Decimal:
    kind, _, arg = fallback.partition(":")
    if kind == "er":
        return sources.er_api_rate(http, arg)
    if kind == "binance":
        return sources.binance_price(http, arg)
    raise sources.SourceError(f"unknown fallback {fallback}")


MAX_QUOTE_AGE = timedelta(days=7)


def _quote(http: httpx.Client, ticker: str, fallback: str | None) -> tuple[Decimal, datetime, str]:
    try:
        _, price, when = sources.yahoo_chart(http, ticker, "5d")
        if datetime.now(UTC) - when > MAX_QUOTE_AGE:
            raise sources.SourceError(f"stale quote from {when:%Y-%m-%d}")
        return price, when, "yahoo"
    except sources.SourceError:
        if fallback is None:
            raise
        logger.info("Yahoo quote for %s failed; using %s", ticker, fallback)
        return _fallback_quote(http, fallback), datetime.now(UTC), fallback.split(":")[0]


def refresh_quotes(db: Any, http: httpx.Client) -> list[str]:
    """Update the latest price of every instrument. Returns symbols that failed."""
    failed: list[str] = []
    usd_egp: Decimal | None = None
    when, src = datetime.now(UTC), "yahoo"
    try:
        usd_egp, when, src = _quote(http, USD_EGP, "er:USD")
    except sources.SourceError as exc:
        logger.warning("USD/EGP quote failed: %s", exc)
    for inst in INSTRUMENTS:
        if _stop:
            break
        try:
            if inst.symbol == "USDEGP":
                if usd_egp is None:
                    raise sources.SourceError("USD/EGP unavailable")
                save_quote(db, inst.symbol, usd_egp, when, src)
                continue
            if inst.yahoo is not None:
                price, as_of, source = _quote(http, inst.yahoo, inst.fallback)
            else:
                if usd_egp is None:
                    raise sources.SourceError("USD/EGP unavailable")
                if inst.symbol == "GOLD21_EGP":
                    usd_oz, as_of, source = _quote(http, GOLD_USD_OZ, None)
                    price = gold21_per_gram(usd_oz, usd_egp)
                else:
                    usd_oz, as_of, source = _quote(http, SILVER_USD_OZ, None)
                    price = silver_per_gram(usd_oz, usd_egp)
            save_quote(db, inst.symbol, price, as_of, source)
        except sources.SourceError as exc:
            if inst.symbol == "GOLD21_EGP" and usd_egp is not None:
                try:  # second source for gold: gold-api spot
                    price = gold21_per_gram(sources.gold_api_usd_per_oz(http), usd_egp)
                    save_quote(db, inst.symbol, price, datetime.now(UTC), "gold-api")
                    continue
                except sources.SourceError:
                    pass
            logger.warning("Quote for %s failed: %s", inst.symbol, exc)
            failed.append(inst.symbol)
        time.sleep(_PAUSE_S)
    return failed


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def refresh_signals(db: Any, today: date) -> int:
    rows = []
    for inst in INSTRUMENTS:
        if not inst.signals_enabled:
            continue
        for draft in build_signals(
            inst.symbol, inst.name, inst.asset_class, load_closes(db, inst.symbol), today
        ):
            rows.append(
                {
                    "symbol": draft.symbol,
                    "kind": draft.kind,
                    "strength": draft.strength,
                    "title": draft.title,
                    "detail": draft.detail,
                    "stats": draft.stats,
                    "created_on": draft.created_on.isoformat(),
                    "expires_on": draft.expires_on.isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
    if rows:
        db.table("market_signals").upsert(rows, on_conflict="symbol,kind,created_on").execute()
    return len(rows)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def run_cycle(db: Any, http: httpx.Client, last_history: datetime | None) -> datetime | None:
    """One quote/signal cycle, with a history reload when due."""
    now = datetime.now(UTC)
    errors: list[str] = []
    status: dict[str, Any] = {}
    if last_history is None or now - last_history > HISTORY_MAX_AGE:
        failed = refresh_history(db, http)
        if len(failed) < len(INSTRUMENTS):
            last_history = now
            status["last_history_at"] = now.isoformat()
        if failed:
            errors.append("history: " + ", ".join(failed))
    failed = refresh_quotes(db, http)
    if len(failed) < len(INSTRUMENTS):
        status["last_quotes_at"] = datetime.now(UTC).isoformat()
    if failed:
        errors.append("quotes: " + ", ".join(failed))
    count = refresh_signals(db, date.today())
    status["last_error"] = "; ".join(errors) or None
    heartbeat(db, **status)
    logger.info("Market cycle done: %d signal(s), %d issue(s)", count, len(errors))
    return last_history


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs every request at INFO (~60 per cycle); keep the log readable.
    for noisy in ("httpx", "httpcore", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    db = get_service_role_client()
    upsert_instruments(db)
    last_history: datetime | None = None
    with httpx.Client(follow_redirects=True) as http:
        while not _stop:
            try:
                last_history = run_cycle(db, http, last_history)
            except Exception as exc:  # never let one bad cycle stop the worker
                logger.error("Market cycle failed: %s", type(exc).__name__, exc_info=exc)
                try:
                    heartbeat(db, last_error=f"cycle failed: {type(exc).__name__}")
                except Exception:
                    pass
            HEARTBEAT_FILE.touch()
            deadline = time.monotonic() + QUOTE_INTERVAL_S + random.uniform(0, 30)
            while not _stop and time.monotonic() < deadline:
                time.sleep(1)
    logger.info("Market worker stopped")


if __name__ == "__main__":
    main()
