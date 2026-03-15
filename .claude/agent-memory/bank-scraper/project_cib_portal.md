---
name: CIB Portal Scraping Notes
description: Login flow, selectors, date/amount format, and structural observations for online.cibeg.com
type: project
---

Portal: https://online.cibeg.com/

CIB's portal is a single-page application (SPA). After authentication the URL typically does not change — the DOM re-renders in-place. Use `networkidle` for goto; fall back to `domcontentloaded` if networkidle times out.

Login form selectors (generic SPA patterns — no stable IDs observed):
- Username: `input[id*='username']` or XPath on placeholder text
- Password: `input[type='password']`
- Submit:   `button[type='submit']` or button containing "Sign In" / "Login"

Post-login dashboard confirmation: `.account-summary`, `.accounts-list`, or classes containing `accountSummary` / `account-widget`.

Login error: `.error-message`, `.alert-danger`, or classes containing `loginError`.

Welcome/announcement modal: may appear after first login. Dismiss via `.modal .close` or `[data-dismiss='modal']`. Non-fatal if absent.

Account Statement navigation: `a[href*='statement']` or text "Account Statement".

Transaction table: class or ID containing "transaction" or "statement".

Date format: `DD-MMM-YYYY` (e.g. `15-Jan-2025`) is primary. Also handles `DD/MM/YYYY`.

Amount format: comma thousands-separator, two decimal places.

Column layout (statement table): Posting Date | Value Date | Description | Debit | Credit | Balance

**Why:** Captured during M2 implementation to avoid re-discovering selectors in future sessions.
**How to apply:** Use these notes when maintaining or debugging `apps/api/app/scrapers/cib.py`. SPA behaviour means selector strategies may need adjustment if the portal undergoes a React/Angular version bump.
