---
name: NBE Portal Facts
description: Live recon data for alahlynet.com.eg — login flow, selectors, data format, OTP
type: project
---

NBE portal is alahlynet.com.eg (NOT ahly-net.com). The old ahly-net.com selectors are dead.

**Why:** The scraper was originally written against a legacy ASP.NET portal. The live portal is an Oracle JET SPA at alahlynet.com.eg rewritten with entirely different selectors and flow.

**How to apply:** Always use the selectors and flow documented here. Never reference ContentPlaceHolder1 or GridView selectors.

## Login URL
`https://www.alahlynet.com.eg/?page=home`

## Login flow — 2 steps
1. Page loads with `#login_username` input. Enter username → click `#username-button`.
2. SPA dynamically renders `#login_password`. Enter password → click `button.btn-login`.
3. Confirm login by waiting for `a:has-text('Logout')` to appear in the DOM.

## OTP detection
- Primary: `#otpSection` element present after login
- Fallback: `input[id*='otp' i]` present
- If detected → raise `ScraperOTPRequired`; never auto-intercept SMS

## Navigation to transactions
1. Click `li.CSA a` (Accounts Summary widget) — flips the card to reveal account list.
2. Account rows are `li.flip-account-list__items`. First row = primary account.
3. Click `a.menu-icon` (3-dots context menu icon) on the first account row.
4. Click `span:has-text('Account Activity')` from the context menu.
5. Wait for `button:has-text('Apply')` — confirms Account Activity page loaded.
6. Click Apply → wait for `oj-table#ViewStatement1 td` to appear (AJAX load).

## Account data extraction
- Account number: `.account-no` text inside `li.flip-account-list__items`
- Account name/type: `.account-name` (often Arabic, e.g. "الحسابات الجارية")
- Balance: `strong.account-value` or pattern `EGP 15,250.75` / `-EGP 79,000.00`

## Transaction table — Oracle JET oj-table
- Table ID: `oj-table#ViewStatement1`
- Cell ID pattern: `ViewStatement1:{row_index}_{col_index}` on `<td>` elements
- Column order (0-based): TxnDate | ValueDate | RefNo | Description | Debit | Credit | Balance
- Date format: `DD Mon YYYY` (e.g. `12 Mar 2026`) — parse with `%d %b %Y`
- Amount format: `EGP 10,100.00` or empty string — strip currency prefix + commas
- Up to 10 rows per page; paginate with `button[title='Next Page']` (check `disabled` attribute)

## Anti-bot notes
- Portal uses Oracle JET which fires XHR after clicking interactive elements.
- Always use `networkidle` wait on goto. Use explicit `wait_for_selector` after clicks.
- Human-like typing via `_type_human` is required on both credential fields.
