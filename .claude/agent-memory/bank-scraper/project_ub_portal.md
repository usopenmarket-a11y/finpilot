---
name: UB portal notes
description: Login selectors, date formats, Dr/Cr amount layout, and dual portal-type handling for ibanking.ub.com.eg
type: project
---

Login URL: `https://ibanking.ub.com.eg/`

Portal type: Unknown at implementation time — selectors cover both SPA (React/Angular, similar to CIB) and WebForms (similar to NBE) patterns.

**Login flow:**
- Username field: `input[id*='UserName']`, `input[id*='customerId']`, or generic placeholder/name XPath fallback.
- Password field: `input[type='password']`.
- Submit: `input[type='submit']`, `button[type='submit']`, or `button[id*='Login']`.
- `_navigate_to_login` tries `networkidle` first (SPA-friendly), falls back to `domcontentloaded` on timeout.
- Bad-credentials indicator: `.failureNotification`, `.error-message`, `.alert-danger`, or `[class*='error-msg']`.
- Dashboard confirmation: `table[id*='AccSummary']`, `.account-summary`, `.accounts-list`, `[class*='account-widget']`, `[class*='account-card']`.

**Date formats:**
- Primary: `DD-MMM-YYYY` (e.g. `15-Jan-2025`) — same as CIB.
- Secondary: `DD/MM/YYYY` and `DD-MM-YYYY`.
- Parser: `_parse_ub_date` — first tries `DD-MMM-YYYY` via regex + `_MONTH_ABBR` dict, then numeric DD/MM/YYYY via regex, then ISO fallback.

**Amount format:**
- Comma thousands-separators: `12,345.67`
- May include a trailing `Dr` / `Cr` suffix indicating debit/credit direction (e.g. `12,345.67 Dr`).
- `_parse_amount` strips `Dr`/`Cr` suffixes via `re.sub(r"\s*[DC]r\.?$", "")` and always returns a positive Decimal. Caller reads direction from the suffix in the raw cell text.

**Transaction table layouts — two variants:**
1. Standard (6 columns): Date | Value Date | Description | Debit | Credit | Balance
2. Compact (4 columns): Date | Description | Amount (Dr/Cr suffix) | Balance
   - `_resolve_txn_columns` detects `amount` column header via regex `^amount$|مبلغ`.
   - `_parse_transaction_row` falls through to the `amount` column if both Debit and Credit columns are empty/zero, then reads the Dr/Cr suffix from the raw cell string for direction.

**Account extraction — dual strategy:**
- SPA path: looks for account summary card by class `account-summary/widget/card` or `data-testid`.
- WebForms path: finds `table[id*='AccSummary']` or first table with "account"/"حساب" in headers.

**Modal handling:** Same pattern as BDC — `.modal .close` or `[data-dismiss='modal']`.

**Why:** Documented during M3 scraper implementation (2026-03-16).
**How to apply:** Use these notes when debugging selector failures or adapting to portal layout changes.
