---
name: NBE Portal Scraping Notes
description: Login selectors, OAAM flow, date format, table structure for alahlynet.com.eg — verified 2026-03-17 via live recon
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
- Password input: `#login_password` — CONFIRMED via CSS (type=text with CSS text-security:disc masking, NOT type=password)
- Password submit: `button.btn-login-2` (60%-width green button) — CONFIRMED via CSS
  - IMPORTANT: `button.btn-login` is the STEP 1 username button — DO NOT use it for step 2
  - Fallback selectors in order: `.loginContainer button.action-button-primary`, `button:not(#username-button).btn-login`

## Post-login confirmation

- Primary: `li.loggedInUser` — nav bar badge with username, always present post-login
- Fallback: `a.no-navigation-logout` — the logout anchor (may be icon-only, no text)
- Avoid: `a:has-text('Logout')` — unreliable since logout link may have no visible text

## OTP detection

- `#otpSection` — dedicated OTP section div
- `input[id*='otp' i]` — any OTP input by id pattern

## Dashboard navigation (post-login)

- Accounts widget: `li.CSA a` — flips the account card to reveal account list
- Account rows: `li.flip-account-list__items`
- Context menu icon (3-dots): `a.menu-icon` — on each account row
- Account Activity menu item: `span:has-text('Account Activity')`
- Apply filter button: `button:has-text('Apply')`

## Transaction table

- Oracle JET table: `oj-table#ViewStatement1`
- Cell selector: `oj-table#ViewStatement1 td`
- Cell ID pattern: `ViewStatement1:{row}_{col}` (deterministic from data binding)
- Pagination: `button[title='Next Page']`
- Column order: 0=Date | 1=Value Date | 2=Ref No | 3=Description | 4=Debit | 5=Credit | 6=Balance

## Account extraction — multi-account (4 accounts per user)

The user has 4 accounts: Savings EGP, Current EGP, Savings USD, Payroll.
All appear as separate `li.flip-account-list__items` rows in the widget.

- Account number: `.account-no` inside `li.flip-account-list__items`
- Account type: `.account-name`
- Balance: `.account-value` (fallback: scan text for currency+amount pattern)

**Multi-account scraping pattern:**
1. Call `_extract_all_accounts()` once — reads ALL rows at once from the widget HTML.
2. For each account at index N, use `page.locator(_SEL_ACCOUNT_ROWS).nth(N).locator(_SEL_MENU_ICON).click()` — NEVER store an ElementHandle across SPA re-renders.
3. After scraping account N's transactions, call `page.go_back()` (wait_until="domcontentloaded") then re-call `_reveal_accounts_widget()` before the next account.
4. `go_back()` can time out on Oracle JET SPAs (SPA keeps persistent XHR connections) — catch PlaywrightTimeoutError and treat as soft warning; `_reveal_accounts_widget` will confirm readiness.
5. Each Transaction.raw_data carries `account_number_masked` for pipeline routing to the correct DB account_id after multi-account upsert.
6. Per-account failures are caught, logged as WARNING, and skipped — one bad account must not abort the entire scrape.

## Data formats

- Transaction dates: `DD Mon YYYY` primary (e.g. `12 Mar 2026`); fallbacks: `DD/MM/YYYY`, `DD-MM-YYYY`
- Amounts: `EGP 10,100.00` or `USD 500.00` — comma thousands separator, currency prefix

## Anti-bot notes

- The OAAM `getOAAMImageForMobile()` call can take several seconds — wait at least 2.5–4s after clicking `#username-button` before checking for the password field
- The `.loginContainer` popup is a full-screen overlay (position:fixed, z-index:100)
- The `#login_password` field is `type=text` with CSS `text-security:disc` — NOT `type=password`

**Why:** Verified live on 2026-03-17 via `recon_nbe.py` + manual JS/CSS analysis of component bundle.
**How to apply:** Use these selectors when maintaining or debugging `apps/api/app/scrapers/nbe.py`. Re-run `recon_nbe.py` whenever portal behavior changes are suspected.
