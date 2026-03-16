# Analytics modules — transaction categorization (via Claude AI), trend
# analysis, credit utilization tracking, and spending summaries.

from app.analytics.categorizer import (
    CATEGORIES,
    CategorizationResult,
    categorize_batch,
    categorize_transaction,
)
from app.analytics.credit import (
    CreditReport,
    CreditUtilization,
    LoanSummary,
    compute_credit_report,
)
from app.analytics.spending import (
    CategoryBreakdown,
    SpendingBreakdown,
    compute_spending_breakdown,
)
from app.analytics.trends import (
    MonthlySnapshot,
    TrendReport,
    compute_trends,
)

__all__ = [
    # categorizer
    "CATEGORIES",
    "CategorizationResult",
    "categorize_transaction",
    "categorize_batch",
    # spending
    "CategoryBreakdown",
    "SpendingBreakdown",
    "compute_spending_breakdown",
    # trends
    "MonthlySnapshot",
    "TrendReport",
    "compute_trends",
    # credit
    "CreditUtilization",
    "LoanSummary",
    "CreditReport",
    "compute_credit_report",
]
