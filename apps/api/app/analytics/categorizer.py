"""Transaction categorization using rule-based matching and Claude Haiku AI fallback.

Rules are applied first with no external I/O.  The AI path is only reached when
no rule matches, and it degrades gracefully (returns "Other") on any API or
parse failure.  If the configured API key is empty the AI path is skipped
entirely.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import anthropic

from app.models.db import Transaction

# ---------------------------------------------------------------------------
# Public category list
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    "Food & Dining",
    "Shopping",
    "Transportation",
    "Utilities",
    "Healthcare",
    "Education",
    "Entertainment",
    "Travel",
    "Groceries",
    "Rent & Housing",
    "Transfers",
    "ATM & Cash",
    "Government & Fees",
    "Insurance",
    "Investment",
    "Loan Repayment",
    "Subscriptions",
    "Income",
    "Other",
]

_CATEGORY_SET: frozenset[str] = frozenset(CATEGORIES)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CategorizationResult:
    """Outcome of categorizing a single transaction."""

    transaction_id: UUID
    category: str
    sub_category: str
    confidence: float  # 0.0–1.0
    method: str  # "ai" | "rule"


# ---------------------------------------------------------------------------
# Rule-based patterns (compiled once at import time)
# ---------------------------------------------------------------------------

# ATM / Cash
_RE_ATM_CASH = re.compile(
    r"\b(atm|cash withdrawal|debit card cash deposit)\b",
    re.IGNORECASE,
)

# Income
_RE_SALARY = re.compile(
    r"(salary|payroll|staffpayroll|راتب|مرتب|أجر|monthly pay|remittance|compensation)",
    re.IGNORECASE,
)
_RE_REWARDS = re.compile(r"\brewards\b", re.IGNORECASE)

# Transfers — internal/external
_RE_TRANSFER = re.compile(
    r"(account to account transfer|ipn transfer|ipn charges|outgoing transfer|"
    r"incoming ach transfer|incoming transfer|from acct|تحويل|"
    r"credit card payment via internet banking|eb-00cc.*card payment|"
    r"\beb-0cc\b.*card payment)",
    re.IGNORECASE,
)
_RE_IPN_BARE = re.compile(r"^\s*IPN\s*$", re.IGNORECASE)

# Loan repayment
_RE_LOAN = re.compile(
    r"(loan interest payment|loan principle payment|loan principal payment)",
    re.IGNORECASE,
)

# Investment / certificates
_RE_INVESTMENT = re.compile(
    r"(certificate.*interest|term deposit.*interest|deposit.*interest|"
    r"investment.*return|maturity proceeds)",
    re.IGNORECASE,
)

# Transportation
_RE_TRANSPORT = re.compile(
    r"\b(uber|careem|didi|lyft|taxi|bolt|indrive|"
    r"cairo metro|metro ticket|bus ticket)\b",
    re.IGNORECASE,
)

# Food & Dining
_RE_FOOD = re.compile(
    r"\b(cafe|coffee|restaurant|pizza|burger|kfc|mcdonald|"
    r"hardee|popeyes|cinnabon|dunkin|starbucks|"
    r"paymob\*cake|dining)\b",
    re.IGNORECASE,
)

# Groceries
_RE_GROCERIES = re.compile(
    r"\b(seoudi|carrefour|spinneys|hyper one|metro market|"
    r"kheir zaman|el-foul|hypermarket|supermarket|"
    r"imtenan|new penni|fresh market|kazyon|"
    r"el tayeb|breadfast|talabat groceries)\b",
    re.IGNORECASE,
)

# Shopping
_RE_SHOPPING = re.compile(
    r"\b(lc waikiki|zara|h&m|shoe room|valu|adidas|nike|"
    r"amazon|noon|jumia|mothercare|ikea|home center|"
    r"carrefour fashion|urart|gumruksuz|shopping)\b",
    re.IGNORECASE,
)

# Utilities / Bill payments
_RE_UTILITIES = re.compile(
    r"\b(my fawry|fawry|sahl|we telecom|vodafone|orange|etisalat|"
    r"electricity|water bill|gas bill|cairo electricity|"
    r"telecom egypt|egynet|nge|utility)\b",
    re.IGNORECASE,
)

# Government & Fees
_RE_FEES = re.compile(
    r"(stamp tax|paper statement fee|annual fee|annual fees|"
    r"maintenance fee|service charge|bank charge|"
    r"outgoing transfer fees|ipn.*charges|sms.*fee|"
    r"card.*fee|account.*fee)",
    re.IGNORECASE,
)

# Subscriptions
_RE_SUBSCRIPTIONS = re.compile(
    r"\b(netflix|spotify|apple|google play|microsoft|"
    r"adobe|claude\.ai|anthropic|chatgpt|openai|"
    r"amazon prime|youtube premium|canva|dropbox|"
    r"subscription|مدفوعات شهرية)\b",
    re.IGNORECASE,
)

# Healthcare
_RE_HEALTHCARE = re.compile(
    r"\b(pharmacy|eczane|hospital|clinic|doctor|lab|"
    r"medical|صيدلية|عيادة|مستشفى|dawaya)\b",
    re.IGNORECASE,
)

# Entertainment
_RE_ENTERTAINMENT = re.compile(
    r"\b(cinema|movie|theatre|concert|vod|"
    r"grand cinema|empire cinema|cine|"
    r"playstation|steam|xbox|gaming)\b",
    re.IGNORECASE,
)

# Travel
_RE_TRAVEL = re.compile(
    r"\b(airline|airways|airport|hotel|booking\.com|"
    r"airbnb|expedia|trivago|egyptair|flydubai|"
    r"turkish airlines|travel agency|سياحة)\b",
    re.IGNORECASE,
)


def _apply_rules(
    description: str,
    amount: Decimal,
    transaction_type: str,
) -> tuple[str, str] | None:
    """Return (category, sub_category) if a rule matches, else None.

    Rules are evaluated in priority order.  The first match wins.
    More specific patterns come before general ones.
    """
    # --- Loan repayment (before transfer catch-all) ---
    if _RE_LOAN.search(description):
        if "interest" in description.lower():
            return ("Loan Repayment", "Interest Payment")
        return ("Loan Repayment", "Principal Payment")

    # --- Investment income ---
    if _RE_INVESTMENT.search(description):
        return ("Investment", "Interest Income")

    # --- Salary / payroll ---
    if _RE_SALARY.search(description):
        return ("Income", "Salary")

    # --- Rewards ---
    if _RE_REWARDS.search(description):
        return ("Income", "Rewards")

    # --- ATM / cash (debit card cash deposit counts as ATM) ---
    if _RE_ATM_CASH.search(description):
        if transaction_type == "credit":
            return ("ATM & Cash", "Cash Deposit")
        return ("ATM & Cash", "Withdrawal")

    # --- Transfers (card payments, IPN, A2A) ---
    if _RE_TRANSFER.search(description) or _RE_IPN_BARE.search(description):
        if transaction_type == "credit":
            return ("Transfers", "Incoming Transfer")
        return ("Transfers", "Outgoing Transfer")

    # --- Government fees & bank charges ---
    if _RE_FEES.search(description):
        return ("Government & Fees", "Bank Fees")

    # --- Subscriptions ---
    if _RE_SUBSCRIPTIONS.search(description):
        return ("Subscriptions", "Digital Subscription")

    # --- Transportation ---
    if _RE_TRANSPORT.search(description):
        return ("Transportation", "Ride-hailing")

    # --- Food & Dining ---
    if _RE_FOOD.search(description):
        return ("Food & Dining", "Restaurant")

    # --- Groceries ---
    if _RE_GROCERIES.search(description):
        return ("Groceries", "Supermarket")

    # --- Shopping ---
    if _RE_SHOPPING.search(description):
        return ("Shopping", "Retail")

    # --- Utilities ---
    if _RE_UTILITIES.search(description):
        return ("Utilities", "Bill Payment")

    # --- Healthcare ---
    if _RE_HEALTHCARE.search(description):
        return ("Healthcare", "Medical")

    # --- Entertainment ---
    if _RE_ENTERTAINMENT.search(description):
        return ("Entertainment", "Leisure")

    # --- Travel ---
    if _RE_TRAVEL.search(description):
        return ("Travel", "Travel")

    return None


# ---------------------------------------------------------------------------
# AI prompt helpers
# ---------------------------------------------------------------------------

_AI_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = (
    "Categorize this Egyptian bank transaction.\n"
    "Description: {description}\n"
    "Amount: {amount} EGP\n"
    "Type: {transaction_type}\n"
    "Available categories: {categories}\n"
    'Reply with JSON only: {{"category": "...", "sub_category": "...", "confidence": 0.0}}'
)


def _build_prompt(description: str, amount: Decimal, transaction_type: str) -> str:
    return _PROMPT_TEMPLATE.format(
        description=description,
        amount=amount,
        transaction_type=transaction_type,
        categories=", ".join(CATEGORIES),
    )


def _parse_ai_response(raw: str) -> tuple[str, str, float]:
    """Parse the JSON blob returned by Claude.

    Returns (category, sub_category, confidence).  Falls back to safe defaults
    on any parse or validation error.
    """
    try:
        # Strip markdown code fences if the model wrapped the JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]

        data: dict = json.loads(cleaned)  # type: ignore[assignment]
        category: str = str(data.get("category", "Other")).strip()
        sub_category: str = str(data.get("sub_category", "")).strip()
        confidence: float = float(data.get("confidence", 0.3))

        # Validate category is known
        if category not in _CATEGORY_SET:
            category = "Other"
            confidence = 0.3

        # Clamp confidence to [0, 1]
        confidence = max(0.0, min(1.0, confidence))
        return (category, sub_category, confidence)

    except Exception:  # noqa: BLE001
        return ("Other", "", 0.3)


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------


async def categorize_transaction(
    description: str,
    amount: Decimal,
    transaction_type: str,
    client: anthropic.AsyncAnthropic,
) -> CategorizationResult:
    """Categorize a single transaction.

    The rule engine is tried first; the AI path is only used when no rule
    matches.  A sentinel UUID is used for the transaction_id because this
    function operates on raw field values rather than a full Transaction object.
    Use `categorize_batch` when working with Transaction instances.
    """
    _SENTINEL_ID = UUID("00000000-0000-0000-0000-000000000000")

    rule_result = _apply_rules(description, amount, transaction_type)
    if rule_result is not None:
        category, sub_category = rule_result
        return CategorizationResult(
            transaction_id=_SENTINEL_ID,
            category=category,
            sub_category=sub_category,
            confidence=1.0,
            method="rule",
        )

    # Check whether the client has a real API key before hitting the network.
    # AsyncAnthropic stores the key as a plain str on ._api_key (private but
    # stable enough for this guard).
    api_key: str = getattr(client, "_api_key", "") or getattr(client, "api_key", "") or ""
    if not api_key:
        return CategorizationResult(
            transaction_id=_SENTINEL_ID,
            category="Other",
            sub_category="",
            confidence=0.3,
            method="rule",
        )

    try:
        prompt = _build_prompt(description, amount, transaction_type)
        message = await client.messages.create(
            model=_AI_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text: str = message.content[0].text  # type: ignore[attr-defined]
        category, sub_category, confidence = _parse_ai_response(raw_text)
    except Exception:  # noqa: BLE001
        category, sub_category, confidence = "Other", "", 0.3

    return CategorizationResult(
        transaction_id=_SENTINEL_ID,
        category=category,
        sub_category=sub_category,
        confidence=confidence,
        method="ai",
    )


async def _categorize_one(
    tx: Transaction,
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    api_key_present: bool,
) -> CategorizationResult:
    """Categorize a single Transaction, respecting the shared semaphore."""
    rule_result = _apply_rules(tx.description, tx.amount, tx.transaction_type)
    if rule_result is not None:
        category, sub_category = rule_result
        return CategorizationResult(
            transaction_id=tx.id,
            category=category,
            sub_category=sub_category,
            confidence=1.0,
            method="rule",
        )

    if not api_key_present:
        return CategorizationResult(
            transaction_id=tx.id,
            category="Other",
            sub_category="",
            confidence=0.3,
            method="rule",
        )

    async with semaphore:
        try:
            prompt = _build_prompt(tx.description, tx.amount, tx.transaction_type)
            message = await client.messages.create(
                model=_AI_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text  # type: ignore[attr-defined]
            category, sub_category, confidence = _parse_ai_response(raw_text)
        except Exception:  # noqa: BLE001
            category, sub_category, confidence = "Other", "", 0.3

    return CategorizationResult(
        transaction_id=tx.id,
        category=category,
        sub_category=sub_category,
        confidence=confidence,
        method="ai",
    )


async def categorize_batch(
    transactions: list[Transaction],
    client: anthropic.AsyncAnthropic,
    concurrency: int = 5,
) -> list[CategorizationResult]:
    """Categorize a list of transactions concurrently.

    Concurrency is limited by a semaphore so we never exceed `concurrency`
    simultaneous Claude API calls.  Rule-based results bypass the semaphore
    entirely and incur no I/O cost.
    """
    if not transactions:
        return []

    api_key: str = getattr(client, "_api_key", "") or getattr(client, "api_key", "") or ""
    api_key_present: bool = bool(api_key)

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [_categorize_one(tx, client, semaphore, api_key_present) for tx in transactions]
    results: list[CategorizationResult] = await asyncio.gather(*tasks)
    return results
