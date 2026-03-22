# Credit Card Repayment Cycle Tracker — PRD

## What it does

A tab inside `/dashboard/credit-cards` that tracks the NBE repayment cycling strategy:
pay cash into the card, withdraw via Fawry, repeat. Auto-classifies existing scraped
transactions and shows totals, fees, remaining balance, and cycle count.

No new Supabase tables. No new API endpoints. Reads data already in DB.

---

## Where it lives

**New tab** added to `CreditCardTabs` in `apps/web/src/components/credit-cards/credit-card-tabs.tsx`:

```
Current Month | Last 6 Months | Unbilled | Unsettled | Repayment Tracker  ← new
```

---

## Data sources (existing DB, no schema changes)

| Field | Source |
|-------|--------|
| `closing_balance` | User input (typed into the tab) |
| `base_cash_amount` | User input (typed into the tab) |
| `credit_limit` | `bank_accounts.credit_limit` |
| `billed_amount` | `bank_accounts.billed_amount` |
| `unbilled_amount` | `bank_accounts.unbilled_amount` |
| Transactions | `transactions` table, already fetched by the page (passed as props) |

The page already fetches 500 CC transactions and passes them to `CreditCardTabs`.
The Repayment Tracker tab receives them and classifies them client-side.

---

## Transaction classification (client-side)

Applied to the CC transactions already available in props:

| Category | Condition |
|----------|-----------|
| `card_payment` | `transaction_type === 'credit'` |
| `fawry_withdrawal` | description contains `FAWRY` (case-insensitive) |
| `fee` | description contains `INTEREST`, `FEE`, or `CHARGE` (case-insensitive) |
| `other` | everything else |

---

## Formulas

```
total_paid            = SUM(amount) WHERE category = 'card_payment'
total_fawry           = SUM(amount) WHERE category = 'fawry_withdrawal'
total_fees            = SUM(amount) WHERE category = 'fee'
remaining_balance     = closing_balance - total_paid
repayment_progress    = (total_paid / closing_balance) * 100   [capped at 100]
fawry_cost            = total_fawry * 0.008
net_reduction         = total_paid - fawry_cost
recycling_loops       = floor(total_paid / base_cash_amount)   [0 if base_cash = 0]
```

---

## UI layout (single tab panel)

### 1. Input row (top)
Two inline number inputs the user fills in:
- **Closing Balance** (EGP) — the statement closing balance
- **Cash Amount per Cycle** (EGP) — how much cash they recycle each loop

A small note: "These values are not saved — re-enter each visit."

### 2. KPI cards (2×2 grid)
| Card | Value |
|------|-------|
| Total Paid | `total_paid` EGP |
| Remaining | `remaining_balance` EGP |
| Recycling Loops | `recycling_loops` (integer) |
| Net Reduction | `net_reduction` EGP |

### 3. Progress bar
Visual bar: `repayment_progress`% filled, labelled "X% repaid"
Color: green < 50%, yellow 50–79%, red ≥ 80% remaining (i.e. low progress)

### 4. Cost breakdown row
Three small stat items inline:
- Fawry withdrawals total: `total_fawry` EGP
- Fawry cost (0.8%): `fawry_cost` EGP
- Fees & interest: `total_fees` EGP

### 5. Transaction table
Classified transactions in date-descending order.
Columns: Date | Description | Category (color-coded badge) | Amount

Badge colors:
- `card_payment` → green
- `fawry_withdrawal` → blue
- `fee` → red
- `other` → gray

---

## Edge cases

| Case | Behaviour |
|------|-----------|
| closing_balance = 0 | Show "No balance due" state, hide KPIs |
| base_cash_amount = 0 | Skip loop calculation, show loops = 0 |
| total_paid > closing_balance | Cap progress at 100%, show "Overpaid" note |
| No card_payment transactions | remaining = closing_balance, loops = 0 |
| No fawry transactions | fawry_cost = 0 |

---

## Implementation scope

- **Only files to touch:**
  - `apps/web/src/components/credit-cards/credit-card-tabs.tsx` — add `'repayment'` tab key + panel
  - `apps/web/src/app/dashboard/credit-cards/page.tsx` — pass CC transactions (already done), also pass `billedAmount` and `creditLimit` from `bank_accounts` so the tab can pre-fill the closing balance

- **No backend changes**
- **No Supabase schema changes**
- **No new files** (component lives inline in `credit-card-tabs.tsx`)

---

## Example

User has closing balance EGP 30,000, cash per cycle EGP 5,000.
Scraped transactions show: Pay 5K, Fawry 5K, Pay 5K, Fawry 5K, Pay 5K, Fawry 5K, Pay 5K.

| Metric | Value |
|--------|-------|
| Total paid | 20,000 EGP |
| Fawry total | 15,000 EGP |
| Fawry cost | 120 EGP |
| Remaining | 10,000 EGP |
| Recycling loops | 4 |
| Progress | 66.67% |
| Net reduction | 19,880 EGP |
