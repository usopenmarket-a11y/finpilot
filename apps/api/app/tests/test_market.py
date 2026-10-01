"""Tests for the market layer: analysis, source parsing and worker logic."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.market import sources, worker
from app.market.analysis import (
    HORIZON,
    backtest,
    build_signals,
    rsi,
    rules_for,
    sma,
)
from app.market.catalog import gold21_per_gram

TODAY = date(2026, 10, 1)


def _series(values: list[float], end: date = TODAY) -> list[tuple[date, Decimal]]:
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), Decimal(str(v))) for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def test_sma_and_rsi_basics() -> None:
    values = [float(v) for v in range(1, 31)]
    assert sma(values, 29, 30) == pytest.approx(15.5)
    assert sma(values, 5, 30) is None
    assert rsi(values, 29) == 100.0  # only gains
    falling = list(reversed(values))
    assert rsi(falling, 29) == pytest.approx(0.0)


def test_backtest_counts_first_day_of_each_episode() -> None:
    # Flat at 100 with two 10-day dips to 90, each followed by recovery.
    values = [100.0] * 60 + [90.0] * 10 + [110.0] * 60 + [90.0] * 10 + [110.0] * 60
    rule = rules_for("gold")["dip"]  # 4% below 30-day average
    result = backtest(values, rule)
    assert result.episodes == 2
    assert result.hit_rate == 1.0
    assert result.median_return > 0
    assert len(values) > HORIZON


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def _dip_history(recovers: bool) -> list[float]:
    """Repeated dips that either recover (rule works) or keep falling (it doesn't)."""
    values: list[float] = []
    level = 100.0
    for _ in range(6):
        values += [level] * 40
        values += [level * 0.9] * 5
        level = level * (1.1 if recovers else 0.85)
        values += [level] * 30
    values += [level] * 40 + [level * 0.9]  # today: a fresh dip
    return values


def test_signal_emitted_only_when_rule_has_worked_before() -> None:
    good = build_signals("GOLD21_EGP", "Gold 21K", "gold", _series(_dip_history(True)), TODAY)
    assert {s.kind for s in good} >= {"dip"}
    dip = next(s for s in good if s.kind == "dip")
    assert dip.stats["episodes"] >= 4
    assert dip.stats["hit_rate"] >= 0.55
    assert "Past patterns do not guarantee future results" in dip.detail
    assert dip.expires_on == TODAY + timedelta(days=3)

    bad = build_signals("GOLD21_EGP", "Gold 21K", "gold", _series(_dip_history(False)), TODAY)
    assert bad == []  # the same dip never paid off historically → no signal


def test_no_signal_on_short_or_stale_history() -> None:
    assert build_signals("X", "X", "gold", _series([100.0] * 50), TODAY) == []
    stale = _series(_dip_history(True), end=TODAY - timedelta(days=10))
    assert build_signals("X", "X", "gold", stale, TODAY) == []


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def _chart(
    closes: list[float | None], stamps: list[int], price: float, market_time: int
) -> dict[str, Any]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": price, "regularMarketTime": market_time},
                    "timestamp": stamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


def test_yahoo_parse_skips_nulls_and_uses_newer_daily_close() -> None:
    day = 86400
    t0 = int(datetime(2026, 9, 28, tzinfo=UTC).timestamp())
    # meta price frozen in 2024 (seen for EGX tickers) but daily data is current
    stale_meta = int(datetime(2024, 7, 23, tzinfo=UTC).timestamp())
    payload = _chart([126.0, None, 128.5], [t0, t0 + day, t0 + 2 * day], 81.2, stale_meta)
    series, price, when = sources.parse_yahoo_chart(payload)
    assert [d.isoformat() for d, _ in series] == ["2026-09-28", "2026-09-30"]
    assert price == Decimal("128.5")
    assert when.date() == date(2026, 9, 30)


def test_yahoo_parse_rejects_bad_payload() -> None:
    with pytest.raises(sources.SourceError):
        sources.parse_yahoo_chart({"chart": {"result": None}})
    with pytest.raises(sources.SourceError):
        sources.parse_yahoo_chart(_chart([], [], 0, 0))


def test_gold_conversion_to_21k_egp_per_gram() -> None:
    # 1 troy ounce = 31.1035 g; 21K = 87.5% pure.
    value = gold21_per_gram(Decimal("4180"), Decimal("52.27"))
    assert value.quantize(Decimal("1")) == Decimal("6147")


def test_derive_per_gram_carries_fx_forward() -> None:
    metal = [(date(2026, 9, 26), Decimal("100")), (date(2026, 9, 28), Decimal("110"))]
    fx = [(date(2026, 9, 25), Decimal("2")), (date(2026, 9, 28), Decimal("3"))]
    out = worker.derive_per_gram(metal, fx, lambda usd, rate: usd * rate)
    assert out == [(date(2026, 9, 26), Decimal("200")), (date(2026, 9, 28), Decimal("330"))]


# ---------------------------------------------------------------------------
# Worker quote fallbacks
# ---------------------------------------------------------------------------


class _FakeDB:
    def __init__(self) -> None:
        self.quotes: dict[str, tuple[Decimal, str]] = {}
        self.daily: list[dict[str, Any]] = []

    def table(self, name: str) -> _FakeDB:
        self._table = name
        return self

    def upsert(self, rows: Any, **_k: Any) -> _FakeDB:
        if self._table == "market_quotes":
            self.quotes[rows["symbol"]] = (Decimal(rows["price"]), rows["source"])
        elif self._table == "market_daily":
            self.daily.extend(rows)
        return self

    def execute(self) -> None:
        return None


def test_quotes_fall_back_and_reject_stale_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    def fake_chart(_http: Any, ticker: str, _range: str = "2y") -> Any:
        if ticker == "EGP=X":
            raise sources.SourceError("yahoo down")
        if ticker == "COMI.CA":
            return [], Decimal("81.2"), now - timedelta(days=800)  # stale
        if ticker == "^CASE30":
            raise sources.SourceError("down")
        return [], Decimal("100"), now

    monkeypatch.setattr(worker, "_PAUSE_S", 0)
    monkeypatch.setattr(sources, "yahoo_chart", fake_chart)
    monkeypatch.setattr(
        sources,
        "er_api_rate",
        lambda _h, base, quote="EGP": Decimal("52") if base == "USD" else Decimal("59"),
    )
    monkeypatch.setattr(sources, "binance_price", lambda _h, pair: Decimal("80000"))
    db = _FakeDB()
    failed = worker.refresh_quotes(db, object())  # type: ignore[arg-type]

    assert db.quotes["USDEGP"] == (Decimal("52"), "er")  # er-api fallback
    assert db.quotes["GOLD21_EGP"][0] == gold21_per_gram(Decimal("100"), Decimal("52"))
    assert "COMI" in failed and "COMI" not in db.quotes  # stale quote rejected
    assert "EGX30" in failed
    assert db.quotes["BTC"][1] == "yahoo"
