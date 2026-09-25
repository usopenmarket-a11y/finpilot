---
name: NBE Portal Facts
description: Live recon data for alahlynet.com.eg — login flow, selectors, data format, OTP, production quirks
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

## Dashboard widget selectors (confirmed 2026-06-16)
- `li.CSA a` — Accounts (Current & Savings)
- `li.TRD a` — Certificates / Deposits
- `li.LON a` — Loans and Finances
- `li.CCA a` — Credit Cards
- `li.PRE a` — Prepaid Cards
Each widget click flips a card, revealing `li.flip-account-list__items` rows inside a
`div.flip-account.{PRODUCT_CODE}` container. Scope HTML parsing to that container to
avoid mixing rows from multiple products.

## Production timing (Render Oregon → NBE Egypt, 2026-06-16)
- Login page load: ~42s
- Dashboard ready (li.loggedInUser): ~34s after login submit
- Total login: ~76s
- CC widget reveal (li.CCA): can take up to 63s post-login
- Widget row rendering after click (KnockoutJS): 5–30s typically
- Timeout constants: _PAGE_LOAD_TIMEOUT_MS=150s, _WAIT_TIMEOUT_MS=240s, _SHORT_TIMEOUT_MS=20s

## Split-sync re-navigation hang (FIXED 2026-06-16)
**Root cause:** `_scrape_certificates`, `_scrape_loans`, and `_scrape_prepaid_cards` were
unconditionally calling `page.goto(_LOGIN_URL, wait_until="domcontentloaded")` at the top of
each helper, even in the split-sync path (`scrape_certificates()`, `scrape_loans()`,
`scrape_prepaid_cards()`) where the page is ALREADY on the dashboard after `_wait_for_dashboard()`.
On Render this redundant goto hung indefinitely (no log output for 9+ minutes).

**Fix applied:** Added "skip goto if already on dashboard" guard to all three helpers, identical
to the guard already in `_scrape_credit_cards` (implemented earlier):
```python
current_url = page.url
on_dashboard = "page=home" in current_url or current_url.rstrip("/") == _LOGIN_URL.rstrip("/")
if not on_dashboard:
    await page.goto(_LOGIN_URL, wait_until="commit", ...)  # "commit" not "domcontentloaded"
    await page.wait_for_selector("li.loggedInUser", timeout=90_000)
    await page.wait_for_selector(WIDGET_SEL, timeout=120_000)
else:
    await page.wait_for_selector(WIDGET_SEL, timeout=_SHORT_TIMEOUT_MS)  # 20s — already hydrated
```
Also changed `wait_until="domcontentloaded"` → `wait_until="commit"` in the re-navigation path
to avoid hangs when Oracle JET is slow to signal domcontentloaded.

## Certificate timeout budget (post-fix)
Split-sync path: login ~76s + _SHORT_TIMEOUT_MS widget check 20s + click 240s + rows 240s = ~576s worst-case.
The client poll cap for certificates in `apps/web/src/lib/api-client.ts` (`syncBankCertificates`)
is 4 minutes (240s). This is too short — the scrape alone can take up to ~576s worst-case.
**Recommendation:** Raise `syncBankCertificates` maxWaitMs to 480_000 (8 min), matching accounts/CC.
(Frontend owns this file — flag to frontend agent or orchestrator.)

## Anti-bot notes
- Portal uses Oracle JET which fires XHR after clicking interactive elements.
- Always use `networkidle` wait on goto. Use explicit `wait_for_selector` after clicks.
- Human-like typing via `_type_human` is required on both credential fields.

## Known empty-state: 0 demand-deposit accounts
When `li.CSA a` is clicked and the bank returns zero current/savings accounts, the widget renders its final state showing the literal text **"0 Accounts"** inside `li.CSA`. The `li.flip-account-list__items` selector correctly never appears. This is a bank-side account-visibility condition — the login and widget click both succeed.

`_reveal_accounts_widget` now returns `bool`:
- `True` = rows appeared, proceed with extraction.
- `False` = confirmed zero-accounts empty state after a 5-second settle window.

Callers in `scrape_accounts()` detect `False` and return an empty `ScraperResult` immediately (no `ScraperTimeoutError`). Callers in `scrape()` skip demand-deposit extraction and continue to CC/cert scraping.

Empty-state detection: `re.compile(r"(?:0|٠)\s*Accounts?\b", re.IGNORECASE)` matched against `await page.locator("li.CSA").inner_text(timeout=2_000)`. Detection is deferred until `_ZERO_ACCOUNTS_SETTLE_S` (5 s) after the widget click to allow the SPA time to hydrate.
