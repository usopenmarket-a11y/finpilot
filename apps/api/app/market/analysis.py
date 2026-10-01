"""Buy-window signals with an honest track record (pure functions).

Three simple, explainable rules, with thresholds scaled to how much each
asset class normally moves:

* ``dip``      — price is well below its 30-day average.
* ``pullback`` — price has fallen well below its 90-day high.
* ``oversold`` — 14-day RSI below 30.

Before a rule produces a signal it is backtested on the instrument's own
history: every past *first day* the rule fired is an episode, and we measure
the price ~30 days (21 trading days) later. A signal is only emitted when the
rule has fired at least ``MIN_EPISODES`` times and was followed by a higher
price at least ``MIN_HIT_RATE`` of the time with a positive median — so a
rule that historically did not work is never shown. Past patterns do not
guarantee future results; the detail text says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from app.market.catalog import AssetClass

HORIZON = 21  # trading days ≈ 30 calendar days
MIN_EPISODES = 4
MIN_HIT_RATE = 0.55
SIGNAL_TTL_DAYS = 3
MAX_DATA_AGE_DAYS = 7  # never signal on stale data

# (dip below 30-day average, pullback from 90-day high)
THRESHOLDS: dict[AssetClass, tuple[float, float]] = {
    "fx": (0.02, 0.04),
    "gold": (0.04, 0.08),
    "index": (0.05, 0.10),
    "stock": (0.07, 0.15),
    "crypto": (0.12, 0.25),
}


def sma(values: Sequence[float], end: int, window: int) -> float | None:
    """Simple moving average of values[end-window+1 .. end]."""
    if end + 1 < window:
        return None
    chunk = values[end + 1 - window : end + 1]
    return sum(chunk) / window


def rsi(values: Sequence[float], end: int, window: int = 14) -> float | None:
    """Classic RSI over the last ``window`` changes ending at ``end``."""
    if end < window:
        return None
    gains = losses = 0.0
    for i in range(end - window + 1, end + 1):
        change = values[i] - values[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change
    if losses == 0:
        return 100.0
    rs = (gains / window) / (losses / window)
    return 100 - 100 / (1 + rs)


def rolling_max(values: Sequence[float], end: int, window: int) -> float | None:
    if end + 1 < window:
        return None
    return max(values[end + 1 - window : end + 1])


Rule = Callable[[Sequence[float], int], bool]


def rules_for(asset_class: AssetClass) -> dict[str, Rule]:
    dip, pullback = THRESHOLDS[asset_class]

    def _dip(v: Sequence[float], i: int) -> bool:
        avg = sma(v, i, 30)
        return avg is not None and v[i] <= avg * (1 - dip)

    def _pullback(v: Sequence[float], i: int) -> bool:
        high = rolling_max(v, i, 90)
        return high is not None and v[i] <= high * (1 - pullback)

    def _oversold(v: Sequence[float], i: int) -> bool:
        r = rsi(v, i)
        return r is not None and r < 30

    return {"dip": _dip, "pullback": _pullback, "oversold": _oversold}


@dataclass
class Backtest:
    episodes: int
    hit_rate: float
    median_return: float
    returns: list[float] = field(default_factory=list)


def backtest(values: Sequence[float], rule: Rule) -> Backtest:
    """Forward HORIZON-day return after each first day the rule fired."""
    returns: list[float] = []
    previous = False
    for i in range(1, len(values) - HORIZON):
        now = rule(values, i)
        if now and not previous:
            returns.append(values[i + HORIZON] / values[i] - 1)
        previous = now
    if not returns:
        return Backtest(0, 0.0, 0.0)
    hits = sum(1 for r in returns if r > 0)
    return Backtest(len(returns), hits / len(returns), median(returns), returns)


@dataclass
class SignalDraft:
    symbol: str
    kind: str
    strength: str
    title: str
    detail: str
    stats: dict[str, float | int]
    created_on: date
    expires_on: date


_RULE_TEXT = {
    "dip": "is {pct} below its 30-day average",
    "pullback": "is {pct} below its 90-day high",
    "oversold": "looks oversold (14-day RSI {rsi:.0f})",
}


def build_signals(
    symbol: str,
    name: str,
    asset_class: AssetClass,
    closes: Sequence[tuple[date, Decimal]],
    today: date,
) -> list[SignalDraft]:
    """Signals for today's (latest) close that pass their own backtest."""
    if len(closes) < 120 or (today - closes[-1][0]).days > MAX_DATA_AGE_DAYS:
        return []
    values = [float(c) for _, c in closes]
    i = len(values) - 1
    fired: list[tuple[str, Backtest, str]] = []
    for kind, rule in rules_for(asset_class).items():
        if not rule(values, i):
            continue
        result = backtest(values, rule)
        if (
            result.episodes < MIN_EPISODES
            or result.hit_rate < MIN_HIT_RATE
            or result.median_return <= 0
        ):
            continue
        if kind == "dip":
            avg = sma(values, i, 30) or values[i]
            text = _RULE_TEXT[kind].format(pct=f"{(1 - values[i] / avg) * 100:.1f}%")
        elif kind == "pullback":
            high = rolling_max(values, i, 90) or values[i]
            text = _RULE_TEXT[kind].format(pct=f"{(1 - values[i] / high) * 100:.1f}%")
        else:
            text = _RULE_TEXT[kind].format(rsi=rsi(values, i) or 0)
        fired.append((kind, result, text))
    strength = "strong" if len(fired) >= 2 else "moderate"
    years = max((closes[-1][0] - closes[0][0]).days / 365, 0.1)
    drafts = []
    for kind, result, text in fired:
        drafts.append(
            SignalDraft(
                symbol=symbol,
                kind=kind,
                strength=strength,
                title=f"{name} {text}",
                detail=(
                    f"In the last {years:.1f} years this happened {result.episodes} times; "
                    f"about 30 days later the price was higher {result.hit_rate:.0%} of the "
                    f"time (median change {result.median_return:+.1%}). Past patterns do not "
                    "guarantee future results."
                ),
                stats={
                    "episodes": result.episodes,
                    "hit_rate": round(result.hit_rate, 4),
                    "median_return": round(result.median_return, 4),
                    "price": values[i],
                },
                created_on=today,
                expires_on=today + timedelta(days=SIGNAL_TTL_DAYS),
            )
        )
    return drafts
