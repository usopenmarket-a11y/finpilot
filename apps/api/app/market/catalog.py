"""Instruments the market worker tracks.

Prices come from Yahoo Finance's public chart endpoint (free, no key, with
daily history), with a free fallback per instrument for the latest quote.
Gold and silver are derived in EGP per gram from the USD futures price and
USD/EGP, so they track the world price; Egyptian shop prices add a premium.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

AssetClass = Literal["fx", "gold", "stock", "index", "crypto"]

TROY_OUNCE_GRAMS = Decimal("31.1034768")
GOLD_21K_PURITY = Decimal("0.875")


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    asset_class: AssetClass
    unit: str
    quote_currency: str
    yahoo: str | None  # None → derived from other series
    signals_enabled: bool = True
    sort_order: int = 100
    fallback: str | None = None  # "er:USD", "er:EUR", "binance:BTCUSDT", ...


INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument(
        "USDEGP", "US dollar", "fx", "EGP per USD", "EGP", "EGP=X", sort_order=10, fallback="er:USD"
    ),
    Instrument(
        "EUREGP", "Euro", "fx", "EGP per EUR", "EGP", "EUREGP=X", sort_order=20, fallback="er:EUR"
    ),
    Instrument("GOLD21_EGP", "Gold 21K", "gold", "EGP per gram", "EGP", None, sort_order=30),
    Instrument(
        "SILVER_EGP",
        "Silver",
        "gold",
        "EGP per gram",
        "EGP",
        None,
        signals_enabled=False,
        sort_order=35,
    ),
    Instrument("EGX30", "EGX30 index", "index", "points", "EGP", "^CASE30", sort_order=40),
    Instrument(
        "COMI",
        "CIB (Commercial International Bank)",
        "stock",
        "EGP per share",
        "EGP",
        "COMI.CA",
        sort_order=50,
    ),
    Instrument("SPX", "S&P 500", "index", "points", "USD", "^GSPC", sort_order=60),
    # Crypto: price tracking only (no buy signals) — the Central Bank of Egypt
    # prohibits trading or promoting crypto without a licence.
    Instrument(
        "BTC",
        "Bitcoin",
        "crypto",
        "USD",
        "USD",
        "BTC-USD",
        signals_enabled=False,
        sort_order=70,
        fallback="binance:BTCUSDT",
    ),
    Instrument(
        "ETH",
        "Ethereum",
        "crypto",
        "USD",
        "USD",
        "ETH-USD",
        signals_enabled=False,
        sort_order=80,
        fallback="binance:ETHUSDT",
    ),
)

# Raw series used to derive gold/silver (not stored as instruments).
GOLD_USD_OZ = "GC=F"
SILVER_USD_OZ = "SI=F"
USD_EGP = "EGP=X"

BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}


def gold21_per_gram(usd_per_oz: Decimal, egp_per_usd: Decimal) -> Decimal:
    return usd_per_oz * egp_per_usd / TROY_OUNCE_GRAMS * GOLD_21K_PURITY


def silver_per_gram(usd_per_oz: Decimal, egp_per_usd: Decimal) -> Decimal:
    return usd_per_oz * egp_per_usd / TROY_OUNCE_GRAMS
