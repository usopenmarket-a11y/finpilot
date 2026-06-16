---
name: NBE Portal Scraping Notes
description: Login selectors, OAAM flow, date format, table structure for alahlynet.com.eg — last verified 2026-06-16 via live post-click recon (all 5 tiles)
type: project
---

Portal: https://www.alahlynet.com.eg/?page=home
Framework: Oracle Banking Digital Experience (OBDX) on Oracle JET + Knockout.js

## Login flow (2-step, OAAM-backed)

**Step 1 selectors — present in initial page HTML (pre-JS render):**
- Username input: `#login_username` (type=text, placeholder="User ID") — CONFIRMED
- Submit button: `#username-button` (class="btn-login action-button-primary") — CONFIRMED

After clicking `#username-button`, the SPA calls `getOAAMImageForMobile()` (OAAM API) to validate the username and load the user's security image. Only on success does `userNameSubmitted(true)` get set, which injects the `.loginContainer` modal popup.

**Step 2 selectors — dynamically injected into `.loginContainer` popup:**
- Password input: `input[id^='login_password'], input.cz-text-box` — CONFIRMED (id rotated to `login_password1` on 2026-04-01; use id-prefix match + class fallback)
- Password submit: `#login-button, button.btn-login-2` — CONFIRMED (both forms seen in production)
  - IMPORTANT: `button.btn-login` is the STEP 1 username button — DO NOT use it for step 2

## Post-login confirmation

- Primary: `li.loggedInUser` — nav bar badge with username, always present post-login
- Fallback: `a.no-navigation-logout` — the logout anchor

## OTP detection

- `#otpSection` — dedicated OTP section div
- `input[id*='otp' i]` — any OTP input by id pattern

## Dashboard product tiles (oj-listview, 2026-06-16)

All product types use `li.{CODE}` tile classes. Clicking `li.{CODE} a` triggers backend AJAX then KnockoutJS renders rows into the flip-card.

| Code | Widget selector | Product |
|------|----------------|---------|
| CSA | `li.CSA a` | Current & Savings Accounts |
| TRD | `li.TRD a` | Certificates / Time Deposits |
| LON | `li.LON a` | Loans & Finances |
| CCA | `li.CCA a` | Credit Cards |
| PRE | `li.PRE a` | Prepaid Cards |

**CRITICAL timing note:** Account rows (`li.flip-account-list__items`) are KnockoutJS-rendered AFTER the tile click, not in the initial page HTML. On Render Oregon → NBE Egypt this takes 5–30s. Always wait with `_WAIT_TIMEOUT_MS = 180_000`. The old `_ZERO_ACCOUNTS_FAST_WINDOW_S = 25s` caused false "0 accounts" — now 60s.

## Account rows (all 5 product types)

All products use the SAME row selector: `li.flip-account-list__items`

Row containers:
- CSA rows inside `div.flip-account.CSA`
- TRD rows inside `div.flip-account.TRD`
- CCA rows inside `div.flip-account.CCA`
- PRE rows inside `div.flip-account.PRE`
- LON rows inside `div.flip-account.LON`

Always scope extraction to the product-specific container to avoid cross-product confusion.

### Field selectors per product (confirmed 2026-06-16 via post-click recon)

**CSA (savings/current accounts):**
- Account number: `div.account-no` (account number, not `span.account-name`)
- Product name: `div.account-name` (Arabic e.g. "توفير بعائد سنوي موظفين")
- Balance: `div.balance-amount` (e.g. "EGP 0.00")
- Context menu: `a.menu-icon` → oj-option `demand-deposit-transactions` → "Account Activity"

**CCA (credit cards):**
- Card info: `div.account-no` (masked card + expiry e.g. "544111******1204 | 07/28")
- Cardholder: `div.account-name`
- Available cash limit: `div.balance-amount` (NOT the billed amount — billed from API intercept)
- API intercept: GET `/digx/v1/cz/creditcardList/creditcarddetails` → `totalbilledamount`

**TRD (certificates / deposits):**
- Same field structure as CSA

**PRE (prepaid cards):**
- Card info: `div.account-no` (masked card + expiry e.g. "411739xxxxxx1286 | Feb-2026")
  - Expiry is pipe-separated: split on `|` and take `[0].strip()` before masking
- Cardholder: `div.account-name`
- Balance: **`span.balance-amount`** (NOT `div.balance-amount` — unique to PRE rows, confirmed 2026-06-16)

**LON (loans and finances):**
- `li.flip-account-list__items` NOT rendered when user has no active loans
- Empty state: `li.oj-listview-no-data-message` appears instead
- Wait selector: combined `f"{_SEL_ACCOUNT_ROWS}, li.oj-listview-no-data-message"` — do not block for 180s on no-data
- Loan reference: `div.account-no`
- Product name: `div.account-name` (Arabic e.g. "جاري مدين بضمان")
- Balance: `div.balance-amount`

## Account type normalisation (Arabic keywords)

`_normalise_account_type` uses these Arabic substrings (lowercased):
- savings: `"توفير"`
- loan: `"قرض"`, `"تمويل"`, `"مديون"`, `"مدين"` (note: مدين ≠ مديون — both needed)
- prepaid_card: `"بطاقة مدفوعة"`
- payroll: `"راتب"`, `"مرتب"`
- certificate: `"شهادة"`

## Transaction table

- Oracle JET table: `oj-table#ViewStatement1`
- Cell ID pattern: `ViewStatement1:{row}_{col}` (deterministic)
- Pagination: `button[title='Next Page']`
- Column order: 0=Date | 1=Value Date | 2=Ref No | 3=Description | 4=Debit | 5=Credit | 6=Balance

## Model change required (flagged 2026-06-16)

`"prepaid_card"` is NOT in `ACCOUNT_TYPES` tuple (`app/models/db.py` line 47) or the DB
`bank_accounts.account_type` CHECK constraint. The architect must add it to both before
the pipeline can persist PRE rows. Loan (`"loan"`) IS already present — no change needed for LON.

## Public split methods (added 2026-06-16)

- `scrape_accounts()` — demand-deposit accounts + transactions (CSA)
- `scrape_credit_cards()` — credit cards only (CCA)
- `scrape_certificates()` — certificates/deposits only (TRD)
- `scrape_loans()` — loans only (LON); returns `[]` when user has no active loans
- `scrape_prepaid_cards()` — prepaid cards only (PRE)
- `scrape()` — all 5 products combined

## Anti-bot notes

- The OAAM `getOAAMImageForMobile()` call can take several seconds — wait at least 2.5–4s
- The `#login_password` field is `type=text` with CSS `text-security:disc` — NOT `type=password`
- NBE element IDs rotate as anti-automation measure (observed 2026-04-01)

**Why:** Verified live on 2026-06-16 via `nbe_post_click_recon.py` — all 5 product tiles clicked with HTML + screenshots captured to `/tmp/finpilot_debug/`.
**How to apply:** Use these selectors when maintaining `apps/api/app/scrapers/nbe.py`. Re-run `nbe_post_click_recon.py <credential_id>` when portal behavior changes.
