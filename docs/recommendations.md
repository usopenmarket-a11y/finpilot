# Investment recommendations

The Recommendations tab opens with two sections: **Your money plan** (built
from the user's own synced data) and **Market opportunities** (built from
free market data). Neither moves money, trades, or connects to a broker.

## Your money plan

`GET /api/v1/recommendations/investment-plan` reads the caller's accounts,
the last 120 days of transactions, borrowed debts, installments, assets, and
preferences on the server, filtered by the JWT user. The pure engine is
`apps/api/app/recommendations/investment_ladder.py`. It answers "what is the
best next use of my money?" in this order:

1. **Starter buffer**: one month of spending in cash.
2. **Credit cards**: pay what is still owed on each statement before the due
   date. Overdue or due-within-7-days statements are `urgent`.
3. **Costly debt**: loans and overdrafts whose rate exceeds the best
   certificate rate. Informal debts are listed as interest-free.
4. **Full buffer**: `emergency_months` of spending (default 3).
5. **Money mix**: after-inflation return of cash, certificates, USD/EUR,
   and gold, valued at live market prices, with each holding's past
   12-month change.
6. **Market opportunities**: `locked` until steps 1–3 are done or
   informational.

Monthly spending is the average of the last three full months of card
purchases plus account debits, excluding the `Transfers`, `Loan Repayment`,
and `Investment` categories so card payments are not counted twice. The
next best action is the most urgent card, with ladder order breaking ties.
Cards that use data older than two days say so and suggest a sync.

### Assumptions and feedback

The bank does not report card interest, overdraft rates, or inflation.
Defaults are 3% a month for cards, 15% a year for inflation, and 3 buffer
months. An NBE `جاري مدين` overdraft without a user rate is estimated at the
pledged certificate rate plus 2 points and shown with low confidence.
`PUT .../investment-plan/assumptions` saves user values to
`user_profiles.preferences.investment_assumptions`; loan rates are kept only
for the caller's own loan accounts. `POST .../investment-plan/feedback`
records done, dismiss, or a 7-day snooze in `investment_feedback`.

## Market opportunities

The `market-worker` Compose service runs `python -m app.market.worker` from
the API image. Every 10 minutes it updates each instrument's latest price
and today's close, recomputes signals, and writes `market_worker_status`.
About once a day it reloads two years of daily history. It health-checks a
heartbeat file rather than HTTP.

| Instrument | Source (fallback) | Signals |
| --- | --- | --- |
| USD/EGP, EUR/EGP | Yahoo `EGP=X`, `EUREGP=X` (open.er-api.com) | yes |
| Gold 21K, silver (EGP/g) | Yahoo `GC=F`, `SI=F` × USD/EGP (gold-api.com) | gold only |
| EGX30, CIB | Yahoo `^CASE30`, `COMI.CA` | when history allows |
| S&P 500 | Yahoo `^GSPC` | yes |
| BTC, ETH | Yahoo (Binance public ticker) | no, price tracking only |

All sources are free and keyless. Gold and silver are world prices; local
shop prices add a premium. Yahoo's EGX30 series has no daily history, so it
is shown without signals. Yahoo's latest-price field for `COMI.CA` can lag by
years; the parser uses the newest daily close instead, and quotes older than
7 days are rejected.

`app/market/analysis.py` checks three rules with thresholds scaled per asset
class: a dip below the 30-day average, a pullback from the 90-day high, and
RSI(14) below 30. A rule produces a signal only when, over the instrument's
own history, it fired at least 4 times and was followed by a higher price
about 30 days (21 trading days) later at least 55% of the time with a
positive median. Signals expire after 3 days unless they repeat. Data older
than 7 days never produces a signal. Crypto has no buy signals because the
Central Bank of Egypt prohibits unlicensed crypto trading and promotion.

`GET /api/v1/market/overview` returns prices, 1-day and 30-day changes,
30-day sparklines, active signals, and freshness (`stale` after 30 minutes
without quotes). The plan values holdings with `market_quotes` and degrades
to "pending market prices" if market data is unavailable.
