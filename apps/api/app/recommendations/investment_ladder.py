"""Personal investment ladder — "what is the best next use of my money?".

Builds an ordered plan from the user's own synced balances, card statements,
loans, certificates, informal debts, installments and assets:

1. Starter buffer — one month of spending in cash.
2. Credit cards — pay statements in full before they accrue interest.
3. Costly debt — loans/overdrafts whose rate exceeds what savings earn.
4. Full safety buffer — ``emergency_months`` of spending in cash.
5. Money mix — real (after-inflation) return of each holding.
6. Market opportunities — only "open" once steps 1–3 are in good shape.

The engine is pure: callers pass a snapshot and assumptions, and get back a
plan of recommendation cards. Rates the bank does not expose (card interest,
overdraft rate, inflation) are explicit assumptions that the user can edit;
every card lists which assumptions it relied on.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

CASH_TYPES = frozenset({"savings", "current", "payroll"})
CERTIFICATE_TYPES = frozenset({"certificate", "deposit", "term_deposit"})
# Debit categories that move money between the user's own products rather
# than spend it (avoids counting a card payment as spending twice).
NON_SPEND_CATEGORIES = frozenset({"Transfers", "Loan Repayment", "Investment"})


class AccountSnapshot(BaseModel):
    """One synced bank product."""

    id: str
    bank: str
    account_type: str
    masked: str
    currency: str = "EGP"
    balance: Decimal = Decimal("0")
    credit_limit: Decimal | None = None
    billed_amount: Decimal | None = None
    minimum_payment: Decimal | None = None
    payment_due_date: date | None = None
    interest_rate: Decimal | None = None  # annual fraction, certificates only
    maturity_date: date | None = None
    product_name: str | None = None
    last_synced_at: datetime | None = None


class TransactionSnapshot(BaseModel):
    """Minimal transaction fields needed for spending/income estimates."""

    account_id: str
    amount: Decimal
    transaction_type: Literal["debit", "credit"]
    category: str | None = None
    transaction_date: date


class AssetSnapshot(BaseModel):
    """A manually tracked asset (gold, foreign currency, property, ...)."""

    asset_type: str
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    currency_code: str | None = None
    value_egp: Decimal | None = None


class Assumptions(BaseModel):
    """Rates the bank does not report. ``user_set`` lists keys the user edited."""

    card_monthly_rate: Decimal = Field(default=Decimal("0.03"), ge=0, le=Decimal("0.10"))
    inflation_annual: Decimal = Field(default=Decimal("0.15"), ge=0, le=Decimal("1"))
    emergency_months: int = Field(default=3, ge=1, le=12)
    # Annual rate per loan/overdraft account id. Missing → estimated.
    loan_rates: dict[str, Decimal] = Field(default_factory=dict)
    user_set: list[str] = Field(default_factory=list)


class PlanInputs(BaseModel):
    accounts: list[AccountSnapshot] = Field(default_factory=list)
    transactions: list[TransactionSnapshot] = Field(default_factory=list)
    borrowed_debts_egp: Decimal = Decimal("0")
    installments_monthly_egp: Decimal = Decimal("0")
    assets: list[AssetSnapshot] = Field(default_factory=list)
    data_as_of: datetime | None = None
    # Latest market prices in EGP keyed by market symbol (USDEGP, EUREGP,
    # GOLD21_EGP, SILVER_EGP) and their change over the past year.
    prices: dict[str, Decimal] = Field(default_factory=dict)
    price_change_1y: dict[str, Decimal] = Field(default_factory=dict)
    market_signals_active: int = 0


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

StepStatus = Literal["done", "action", "info", "locked"]


class RecommendationCard(BaseModel):
    id: str = Field(description="Stable key, used for done/snooze/dismiss feedback")
    step: str
    priority: Literal["urgent", "high", "medium", "low"]
    title: str
    why: str
    amount_egp: Decimal | None = None
    impact_monthly_egp: Decimal | None = Field(
        default=None, description="Estimated EGP saved or earned per month"
    )
    risk: str
    horizon: str
    confidence: Literal["high", "medium", "low"]
    assumptions_used: list[str] = Field(default_factory=list)


class LadderStep(BaseModel):
    key: str
    title: str
    status: StepStatus
    summary: str
    cards: list[RecommendationCard] = Field(default_factory=list)


class HoldingBucket(BaseModel):
    key: str
    label: str
    value_egp: Decimal | None
    detail: str
    real_return_annual: Decimal | None = Field(
        default=None, description="Nominal return minus inflation; None if unknown"
    )


class Snapshot(BaseModel):
    monthly_spend_egp: Decimal
    monthly_income_egp: Decimal
    months_measured: int
    cash_egp: Decimal
    card_balance_egp: Decimal
    card_statement_due_egp: Decimal
    loan_balance_egp: Decimal
    borrowed_debts_egp: Decimal
    installments_monthly_egp: Decimal
    certificates_egp: Decimal
    best_certificate_rate: Decimal | None
    buffer_months: Decimal | None


class LoanRate(BaseModel):
    """A loan/overdraft and the annual rate the ladder used for it."""

    id: str
    label: str
    masked: str
    balance_egp: Decimal
    rate_annual: Decimal | None
    source: str = Field(description="'your rate', an estimate description, or 'unknown'")


class InvestmentPlan(BaseModel):
    generated_on: date
    data_as_of: datetime | None
    snapshot: Snapshot
    assumptions: Assumptions
    steps: list[LadderStep]
    holdings: list[HoldingBucket]
    loans: list[LoanRate] = Field(default_factory=list)
    market_gate_open: bool
    next_best_action: RecommendationCard | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _egp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _pct(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.1'))}%"


def _fmt(value: Decimal) -> str:
    return f"EGP {_egp(value):,}"


_STALE_AFTER_DAYS = 2


def _sync_note(account: AccountSnapshot, today: date) -> str:
    """Warn when a recommendation relies on data that may be out of date."""
    if account.last_synced_at is None:
        return " (last sync time unknown — sync this account to confirm)"
    age = (today - account.last_synced_at.date()).days
    if age >= _STALE_AFTER_DAYS:
        return f" (as of the last sync on {account.last_synced_at:%d %b} — sync to confirm)"
    return ""


def _month_key(d: date) -> tuple[int, int]:
    return d.year, d.month


def estimate_monthly_flows(
    accounts: list[AccountSnapshot], transactions: list[TransactionSnapshot], today: date
) -> tuple[Decimal, Decimal, int]:
    """Average monthly spending and income over the last 3 full months.

    Spending = card purchases + debits from deposit/overdraft accounts,
    excluding transfers between the user's own products. Income = credits
    categorised as Income.
    """
    by_id = {a.id: a for a in accounts}
    months: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(3):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append((y, m))
    spend = dict.fromkeys(months, Decimal("0"))
    income = dict.fromkeys(months, Decimal("0"))
    seen: set[tuple[int, int]] = set()
    for t in transactions:
        key = _month_key(t.transaction_date)
        if key not in spend:
            continue
        account = by_id.get(t.account_id)
        if account is None or account.account_type in CERTIFICATE_TYPES:
            continue
        seen.add(key)
        if t.transaction_type == "debit" and t.category not in NON_SPEND_CATEGORIES:
            spend[key] += t.amount
        elif t.transaction_type == "credit" and t.category == "Income":
            income[key] += t.amount
    measured = [k for k in months if k in seen]
    if not measured:
        return Decimal("0"), Decimal("0"), 0
    n = Decimal(len(measured))
    return (
        sum((spend[k] for k in measured), Decimal("0")) / n,
        sum((income[k] for k in measured), Decimal("0")) / n,
        len(measured),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def build_investment_plan(
    inputs: PlanInputs, assumptions: Assumptions, today: date
) -> InvestmentPlan:
    """Compute the ordered personal ladder for one user."""
    accounts = inputs.accounts
    spend, income, measured = estimate_monthly_flows(accounts, inputs.transactions, today)

    egp = [a for a in accounts if a.currency.upper() == "EGP"]
    cash = sum(
        (a.balance for a in egp if a.account_type in CASH_TYPES and a.balance > 0), Decimal("0")
    )
    cards = [a for a in egp if a.account_type == "credit_card" and a.balance > 0]
    loans = [a for a in egp if a.account_type == "loan" and a.balance > 0]
    certs = [a for a in egp if a.account_type in CERTIFICATE_TYPES and a.balance > 0]
    rated_certs = [c for c in certs if c.interest_rate]
    best_cert_rate = max((c.interest_rate for c in rated_certs if c.interest_rate), default=None)
    card_balance = sum((c.balance for c in cards), Decimal("0"))
    statement_due = sum((c.billed_amount or Decimal("0") for c in cards), Decimal("0"))
    loan_balance = sum((loan.balance for loan in loans), Decimal("0"))
    certificates = sum((c.balance for c in certs), Decimal("0"))
    buffer_months = (cash / spend).quantize(Decimal("0.1")) if spend > 0 else None

    snapshot = Snapshot(
        monthly_spend_egp=_egp(spend),
        monthly_income_egp=_egp(income),
        months_measured=measured,
        cash_egp=_egp(cash),
        card_balance_egp=_egp(card_balance),
        card_statement_due_egp=_egp(statement_due),
        loan_balance_egp=_egp(loan_balance),
        borrowed_debts_egp=_egp(inputs.borrowed_debts_egp),
        installments_monthly_egp=_egp(inputs.installments_monthly_egp),
        certificates_egp=_egp(certificates),
        best_certificate_rate=best_cert_rate,
        buffer_months=buffer_months,
    )

    steps = [
        _starter_buffer_step(spend, cash, measured),
        _card_step(cards, cash, assumptions, today),
        _costly_debt_step(
            loans, best_cert_rate, rated_certs, assumptions, today, inputs.borrowed_debts_egp
        ),
        _full_buffer_step(spend, cash, measured, assumptions),
    ]
    gate_open = all(s.status in ("done", "info") for s in steps[:3])
    holdings = _holdings(
        accounts, inputs.assets, assumptions, inputs.prices, inputs.price_change_1y
    )
    steps.append(_mix_step(holdings, certificates, cash, assumptions, gate_open))
    flagged = inputs.market_signals_active
    flagged_text = (
        f"{flagged} buy window(s) are flagged right now — see Market opportunities below."
        if flagged
        else "No buy windows are flagged right now."
    )
    steps.append(
        LadderStep(
            key="market",
            title="Market opportunities",
            status="info" if gate_open else "locked",
            summary=(
                f"Your foundations are in place. {flagged_text}"
                if gate_open
                else "Wait until the steps above are in good shape — buying assets while "
                "paying card or costly-loan interest usually loses money. "
                + (f"({flagged} buy window(s) are flagged below for later.)" if flagged else "")
            ).strip(),
        )
    )

    next_action = next_best_action(steps)
    return InvestmentPlan(
        generated_on=today,
        data_as_of=inputs.data_as_of,
        snapshot=snapshot,
        assumptions=assumptions,
        steps=steps,
        holdings=holdings,
        loans=[
            LoanRate(
                id=loan.id,
                label=loan.product_name or f"{loan.bank} loan",
                masked=loan.masked,
                balance_egp=_egp(loan.balance),
                rate_annual=rate,
                source=source,
            )
            for loan in loans
            for rate, source in [_loan_rate(loan, best_cert_rate, assumptions)]
        ],
        market_gate_open=gate_open,
        next_best_action=next_action,
    )


_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def next_best_action(steps: list[LadderStep]) -> RecommendationCard | None:
    """Most urgent actionable card; ladder order breaks ties within a priority."""
    actionable = [
        (i, j, card)
        for i, step in enumerate(steps)
        if step.status == "action"
        for j, card in enumerate(step.cards)
    ]
    if not actionable:
        return None
    return min(actionable, key=lambda t: (_PRIORITY_ORDER[t[2].priority], t[0], t[1]))[2]


def _starter_buffer_step(spend: Decimal, cash: Decimal, measured: int) -> LadderStep:
    title = "Starter buffer (1 month of spending)"
    if measured == 0 or spend <= 0:
        return LadderStep(
            key="starter_buffer",
            title=title,
            status="info",
            summary="Not enough synced transactions to estimate monthly spending yet.",
        )
    if cash >= spend:
        return LadderStep(
            key="starter_buffer",
            title=title,
            status="done",
            summary=f"You hold {_fmt(cash)} in cash, at least one month of spending ({_fmt(spend)}).",
        )
    gap = spend - cash
    return LadderStep(
        key="starter_buffer",
        title=title,
        status="action",
        summary=f"Cash {_fmt(cash)} covers less than one month of spending ({_fmt(spend)}).",
        cards=[
            RecommendationCard(
                id="starter-buffer",
                step="starter_buffer",
                priority="high",
                title=f"Keep {_fmt(gap)} more in cash",
                why=(
                    f"You spend about {_fmt(spend)} a month (last {measured} month(s)) but hold "
                    f"{_fmt(cash)} in your accounts. Without a cushion, any surprise expense "
                    "lands on a credit card at card interest."
                ),
                amount_egp=_egp(gap),
                risk="None — cash in a savings account.",
                horizon="Next 1–2 months",
                confidence="medium",
            )
        ],
    )


def _card_step(
    cards: list[AccountSnapshot], cash: Decimal, a: Assumptions, today: date
) -> LadderStep:
    title = "Credit cards: pay statements in full"
    if not cards:
        return LadderStep(key="cards", title=title, status="done", summary="No card balance.")
    cards_out: list[RecommendationCard] = []
    total_due = Decimal("0")
    for c in cards:
        billed = c.billed_amount or Decimal("0")
        if billed <= 0:
            continue
        # Payments after the statement reduce what is still owed on it.
        to_pay = min(billed, c.balance)
        if to_pay <= 0:
            continue
        total_due += to_pay
        minimum = min(c.minimum_payment or Decimal("0"), to_pay)
        carried = max(to_pay - minimum, Decimal("0"))
        interest = carried * a.card_monthly_rate
        days = (c.payment_due_date - today).days if c.payment_due_date else None
        overdue = days is not None and days < 0
        when = (
            f"overdue since {c.payment_due_date:%d %b}"
            if overdue and c.payment_due_date
            else f"due in {days} day(s) ({c.payment_due_date:%d %b})"
            if days is not None and c.payment_due_date
            else "due date unknown"
        )
        paid_note = (
            f" You have already paid {_fmt(billed - to_pay)} of the {_fmt(billed)} statement."
            if to_pay < billed
            else ""
        )
        cards_out.append(
            RecommendationCard(
                id=f"card-pay:{c.id}:{c.payment_due_date or 'nodate'}",
                step="cards",
                priority="urgent" if overdue or (days is not None and days <= 7) else "high",
                title=f"Pay {_fmt(to_pay)} on the {c.bank} card {c.masked} statement",
                why=(
                    f"The statement is {when}{_sync_note(c, today)}.{paid_note} Paying only "
                    f"the minimum ({_fmt(minimum)}) carries {_fmt(carried)} at about "
                    f"{_pct(a.card_monthly_rate)} a month — roughly {_fmt(interest)} interest "
                    "next month, more than any savings product earns"
                    + (", plus late fees once overdue." if overdue else ".")
                ),
                amount_egp=_egp(to_pay),
                impact_monthly_egp=_egp(interest),
                risk="None — guaranteed saving.",
                horizon="Now" if overdue else "Before the due date",
                confidence="high" if "card_monthly_rate" in a.user_set else "medium",
                assumptions_used=["card_monthly_rate"],
            )
        )
    cards_out.sort(
        key=lambda card: (card.priority != "urgent", -(card.impact_monthly_egp or Decimal("0")))
    )
    if not cards_out:
        return LadderStep(
            key="cards",
            title=title,
            status="done",
            summary="No statement balance currently due; new purchases are interest-free until billed.",
        )
    summary = f"{_fmt(total_due)} of statements to clear."
    if cash < total_due:
        summary += (
            f" Your cash ({_fmt(cash)}) does not cover it — pay as much as possible, "
            "largest interest first, and avoid new card spending until cleared."
        )
    return LadderStep(key="cards", title=title, status="action", summary=summary, cards=cards_out)


def _loan_rate(
    loan: AccountSnapshot, best_cert_rate: Decimal | None, a: Assumptions
) -> tuple[Decimal | None, str]:
    """Return (annual rate, source) for a loan/overdraft account."""
    if loan.id in a.loan_rates:
        return a.loan_rates[loan.id], "your rate"
    name = loan.product_name or ""
    if "مدين" in name and best_cert_rate is not None:
        # NBE secured overdrafts are typically priced at the pledged
        # certificate's rate plus a margin; 2 points is a conservative guess.
        return best_cert_rate + Decimal("0.02"), "estimated: certificate rate + 2 points"
    return None, "unknown"


def _costly_debt_step(
    loans: list[AccountSnapshot],
    best_cert_rate: Decimal | None,
    rated_certs: list[AccountSnapshot],
    a: Assumptions,
    today: date,
    borrowed: Decimal = Decimal("0"),
) -> LadderStep:
    title = "Loans and overdrafts vs what your savings earn"
    informal = (
        f" You also owe {_fmt(borrowed)} to people (Debts tab); FinPilot treats it as "
        "interest-free, so repay it on the terms you agreed."
        if borrowed > 0
        else ""
    )
    if not loans:
        return LadderStep(
            key="costly_debt",
            title=title,
            status="info" if borrowed > 0 else "done",
            summary="No bank loans." + informal,
        )
    cards_out: list[RecommendationCard] = []
    unknown: list[str] = []
    for loan in loans:
        rate, source = _loan_rate(loan, best_cert_rate, a)
        label = loan.product_name or f"{loan.bank} loan {loan.masked}"
        if rate is None:
            unknown.append(f"{loan.bank} {loan.masked}")
            continue
        monthly_cost = loan.balance * rate / 12
        if best_cert_rate is None or rate <= best_cert_rate:
            continue
        spread = rate - best_cert_rate
        net_monthly = loan.balance * spread / 12
        maturing = sorted(
            (c for c in rated_certs if c.maturity_date and c.maturity_date >= today),
            key=lambda c: c.maturity_date or today,
        )
        hint = (
            f" Certificate {maturing[0].masked} matures {maturing[0].maturity_date:%b %Y}; "
            "using its proceeds to clear this would end the cost."
            if maturing
            else ""
        )
        cards_out.append(
            RecommendationCard(
                id=f"loan-spread:{loan.id}",
                step="costly_debt",
                priority="medium",
                title=f"Pay down {label} ({loan.masked}) before investing more",
                why=(
                    f"{_fmt(loan.balance)} costs about {_pct(rate)} a year ({source}) — "
                    f"{_fmt(monthly_cost)} a month — while your best certificate earns "
                    f"{_pct(best_cert_rate)}. Holding both costs you about "
                    f"{_fmt(net_monthly)} a month.{hint} Breaking a certificate early "
                    "usually carries a penalty, so prefer spare cash or maturity proceeds."
                ),
                amount_egp=_egp(loan.balance),
                impact_monthly_egp=_egp(net_monthly),
                risk="None — every pound repaid saves the loan rate.",
                horizon="As cash allows",
                confidence="high" if source == "your rate" else "low",
                assumptions_used=[] if source == "your rate" else [f"loan_rates.{loan.id}"],
            )
        )
    if unknown:
        cards_out.append(
            RecommendationCard(
                id="loan-rate-missing",
                step="costly_debt",
                priority="low",
                title="Add your loan interest rates",
                why=(
                    "The bank portal does not show the rate for "
                    + ", ".join(unknown)
                    + ". Add it under Assumptions so FinPilot can compare it with your savings."
                ),
                risk="—",
                horizon="Once",
                confidence="high",
            )
        )
    status: StepStatus = "action" if any(c.priority != "low" for c in cards_out) else "info"
    summary = (
        "Some debt costs more than your savings earn."
        if status == "action"
        else "No loan costs more than your certificates earn"
        + (" (some rates unknown)." if unknown else ".")
    )
    return LadderStep(
        key="costly_debt", title=title, status=status, summary=summary + informal, cards=cards_out
    )


def _full_buffer_step(spend: Decimal, cash: Decimal, measured: int, a: Assumptions) -> LadderStep:
    title = f"Full safety buffer ({a.emergency_months} months)"
    if measured == 0 or spend <= 0:
        return LadderStep(
            key="full_buffer", title=title, status="info", summary="Waiting for spending data."
        )
    target = spend * a.emergency_months
    if cash >= target:
        return LadderStep(
            key="full_buffer",
            title=title,
            status="done",
            summary=f"Cash {_fmt(cash)} covers {a.emergency_months} months of spending.",
        )
    return LadderStep(
        key="full_buffer",
        title=title,
        status="action",
        summary=f"Target {_fmt(target)}; you have {_fmt(cash)}.",
        cards=[
            RecommendationCard(
                id="full-buffer",
                step="full_buffer",
                priority="low",
                title=f"Grow your cash buffer to {_fmt(target)}",
                why=(
                    f"{a.emergency_months} months of spending protects you from job or health "
                    "shocks without breaking certificates or borrowing. Keep it in a "
                    "savings account you can withdraw from at once."
                ),
                amount_egp=_egp(target - cash),
                risk="None.",
                horizon="Over the next 6–12 months",
                confidence="medium",
                assumptions_used=["emergency_months"],
            )
        ],
    )


_FX_SYMBOL = {"USD": "USDEGP", "EUR": "EUREGP"}


def _karat_factor(name: str) -> Decimal:
    """Price factor relative to 21K, read from the asset name (default 21K)."""
    if "24" in name:
        return Decimal("1") / Decimal("0.875")
    if "18" in name:
        return Decimal("0.75") / Decimal("0.875")
    return Decimal("1")


def _past_year_line(
    inputs_change: dict[str, Decimal], symbol: str, label: str, a: Assumptions
) -> tuple[str, Decimal | None]:
    change = inputs_change.get(symbol)
    if change is None:
        return "", None
    return (
        f" {label} changed {_pct(change)} in EGP over the past 12 months "
        f"({_pct(change - a.inflation_annual)} after inflation; past performance, not a forecast).",
        change - a.inflation_annual,
    )


def _holdings(
    accounts: list[AccountSnapshot],
    assets: list[AssetSnapshot],
    a: Assumptions,
    prices: dict[str, Decimal] | None = None,
    change_1y: dict[str, Decimal] | None = None,
) -> list[HoldingBucket]:
    prices = prices or {}
    change_1y = change_1y or {}
    egp_cash = sum(
        (
            x.balance
            for x in accounts
            if x.currency.upper() == "EGP" and x.account_type in CASH_TYPES and x.balance > 0
        ),
        Decimal("0"),
    )
    certs = [x for x in accounts if x.account_type in CERTIFICATE_TYPES and x.balance > 0]
    cert_value = sum((c.balance for c in certs), Decimal("0"))
    weighted = (
        sum((c.balance * (c.interest_rate or 0) for c in certs), Decimal("0")) / cert_value
        if cert_value > 0
        else None
    )
    fx_accounts = [
        x
        for x in accounts
        if x.currency.upper() != "EGP" and x.account_type in CASH_TYPES and x.balance > 0
    ]
    fx_assets = [s for s in assets if s.asset_type == "foreign_currency"]
    gold = [s for s in assets if s.asset_type in ("gold", "silver")]
    other = [s for s in assets if s.asset_type not in ("foreign_currency", "gold", "silver")]

    def _qty(items: list[AssetSnapshot]) -> str:
        parts = [f"{s.quantity or 0:g} {s.unit or ''}".strip() + f" {s.name}" for s in items]
        return ", ".join(parts) if parts else "none recorded"

    # Foreign currency: bank balances plus cash recorded as assets.
    fx_holdings = [
        (x.currency.upper(), x.balance, f"{x.currency} {x.balance:,} in {x.bank} {x.masked}")
        for x in fx_accounts
    ] + [
        (
            (s.currency_code or s.unit or "").upper(),
            s.quantity or Decimal("0"),
            f"{s.quantity or 0:g} {s.unit or ''} ({s.name})",
        )
        for s in fx_assets
    ]
    fx_value: Decimal | None = Decimal("0")
    for currency, amount, _ in fx_holdings:
        rate = prices.get(_FX_SYMBOL.get(currency, ""))
        if rate is None:
            fx_value = None
            break
        fx_value = (fx_value or Decimal("0")) + amount * rate
    fx_detail = ", ".join(d for _, _, d in fx_holdings) or "none recorded"
    fx_line, fx_real = _past_year_line(change_1y, "USDEGP", "The US dollar", a)

    gold_value: Decimal | None = Decimal("0")
    for item in gold:
        symbol = "GOLD21_EGP" if item.asset_type == "gold" else "SILVER_EGP"
        price = prices.get(symbol)
        grams = item.quantity or Decimal("0")
        if price is None or (item.unit or "grams").lower() not in ("grams", "gram", "g"):
            gold_value = None
            break
        factor = _karat_factor(item.name) if item.asset_type == "gold" else Decimal("1")
        gold_value = (gold_value or Decimal("0")) + grams * price * factor
    gold_line, gold_real = _past_year_line(change_1y, "GOLD21_EGP", "Gold", a)

    return [
        HoldingBucket(
            key="egp_cash",
            label="EGP cash",
            value_egp=_egp(egp_cash),
            detail="Savings, current and payroll accounts",
            real_return_annual=-a.inflation_annual,
        ),
        HoldingBucket(
            key="egp_certificates",
            label="EGP certificates",
            value_egp=_egp(cert_value),
            detail=(
                f"Average rate {_pct(weighted)}" if weighted is not None else "No certificates"
            ),
            real_return_annual=(weighted - a.inflation_annual) if weighted is not None else None,
        ),
        HoldingBucket(
            key="foreign_currency",
            label="USD / EUR",
            value_egp=_egp(fx_value) if fx_value is not None and fx_holdings else None,
            detail=fx_detail
            + (
                " — at today's rates."
                if fx_value is not None and fx_holdings
                else " — EGP value pending market prices."
            )
            + fx_line,
            real_return_annual=fx_real,
        ),
        HoldingBucket(
            key="gold",
            label="Gold & silver",
            value_egp=_egp(gold_value) if gold_value is not None and gold else None,
            detail=_qty(gold)
            + (
                " — at world price, 21K unless the name says 24K/18K; shop prices add a premium."
                if gold_value is not None and gold
                else " — EGP value pending market prices."
            )
            + gold_line,
            real_return_annual=gold_real,
        ),
        HoldingBucket(
            key="other_assets",
            label="Property & other",
            value_egp=_egp(sum((s.value_egp or Decimal("0") for s in other), Decimal("0"))),
            detail=_qty(other),
        ),
    ]


def _mix_step(
    holdings: list[HoldingBucket],
    certificates: Decimal,
    cash: Decimal,
    a: Assumptions,
    gate_open: bool,
) -> LadderStep:
    title = "Your money mix (after inflation)"
    cert = next(h for h in holdings if h.key == "egp_certificates")
    lines = [f"Inflation assumption {_pct(a.inflation_annual)} a year."]
    if cert.real_return_annual is not None:
        lines.append(
            f"Certificates earn {_pct(cert.real_return_annual + a.inflation_annual)} — "
            f"{_pct(cert.real_return_annual)} after inflation."
        )
    lines.append(f"Idle cash loses about {_pct(a.inflation_annual)} of buying power a year.")
    cards_out: list[RecommendationCard] = []
    if (
        gate_open
        and cash > 0
        and cert.real_return_annual is not None
        and cert.real_return_annual > 0
    ):
        cards_out.append(
            RecommendationCard(
                id="mix-idle-cash",
                step="mix",
                priority="low",
                title="Put cash above your buffer to work",
                why=(
                    "Money beyond your safety buffer sitting in a current account loses "
                    f"{_pct(a.inflation_annual)} a year to inflation, while certificates "
                    f"currently beat inflation by {_pct(cert.real_return_annual)}. Consider "
                    "splitting new savings between certificates (EGP income) and gold/USD "
                    "(protection if the pound weakens)."
                ),
                risk="Low for certificates; gold/USD prices move both ways.",
                horizon="12+ months",
                confidence="low",
                assumptions_used=["inflation_annual"],
            )
        )
    return LadderStep(
        key="mix",
        title=title,
        status="action" if cards_out else "info",
        summary=" ".join(lines),
        cards=cards_out,
    )
