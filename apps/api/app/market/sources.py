"""Free market data sources (no API keys).

* Yahoo Finance chart endpoint — daily history and latest price for FX,
  futures, EGX and US indices, and crypto.
* open.er-api.com — latest FX rates (fallback for USD/EGP, EUR/EGP).
* gold-api.com — latest gold spot in USD (fallback for gold).
* Binance public ticker — latest crypto price (fallback for BTC/ETH).

Every call has a timeout and raises ``SourceError`` on any failure so the
worker can fall back or skip without crashing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(20.0)
_HEADERS = {"User-Agent": "Mozilla/5.0 (FinPilot market worker)"}


class SourceError(Exception):
    """A market data source failed or returned unusable data."""


def _get_json(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> Any:
    try:
        resp = client.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(f"{url}: {type(exc).__name__}") from exc


def _positive(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SourceError("non-numeric price") from exc
    if not d.is_finite() or d <= 0:
        raise SourceError("non-positive price")
    return d


def parse_yahoo_chart(payload: Any) -> tuple[list[tuple[date, Decimal]], Decimal, datetime]:
    """Return (daily closes oldest→newest, latest price, latest time) from a chart payload."""
    try:
        result = payload["chart"]["result"][0]
        meta = result["meta"]
        stamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError("unexpected Yahoo chart shape") from exc
    daily: dict[date, tuple[Decimal, datetime]] = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        try:
            when_ts = datetime.fromtimestamp(int(ts), tz=UTC)
            daily[when_ts.date()] = (_positive(close), when_ts)
        except SourceError:
            continue
    series = sorted((d, v[0]) for d, v in daily.items())
    when = datetime.fromtimestamp(int(meta.get("regularMarketTime") or 0), tz=UTC)
    price: Decimal | None
    try:
        price = _positive(meta.get("regularMarketPrice"))
    except SourceError:
        price = None
    # Yahoo's regularMarketPrice can lag far behind the daily series (seen for
    # EGX tickers); use the newest daily close when it is more recent.
    if series and (price is None or series[-1][0] > when.date()):
        price, when = daily[series[-1][0]]
    if price is None:
        raise SourceError("no price")
    return series, price, when


def yahoo_chart(
    client: httpx.Client, ticker: str, range_: str = "2y"
) -> tuple[list[tuple[date, Decimal]], Decimal, datetime]:
    payload = _get_json(
        client,
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        {"range": range_, "interval": "1d"},
    )
    return parse_yahoo_chart(payload)


def er_api_rate(client: httpx.Client, base: str, quote: str = "EGP") -> Decimal:
    payload = _get_json(client, f"https://open.er-api.com/v6/latest/{base}")
    if not isinstance(payload, dict) or payload.get("result") != "success":
        raise SourceError("er-api returned no result")
    return _positive((payload.get("rates") or {}).get(quote))


def gold_api_usd_per_oz(client: httpx.Client, metal: str = "XAU") -> Decimal:
    payload = _get_json(client, f"https://api.gold-api.com/price/{metal}")
    return _positive(payload.get("price") if isinstance(payload, dict) else None)


def binance_price(client: httpx.Client, pair: str) -> Decimal:
    payload = _get_json(client, "https://api.binance.com/api/v3/ticker/price", {"symbol": pair})
    return _positive(payload.get("price") if isinstance(payload, dict) else None)
