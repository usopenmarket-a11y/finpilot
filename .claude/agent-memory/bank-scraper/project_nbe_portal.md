---
name: NBE Portal Scraping Notes
description: Login flow, selectors, date/amount format, and structural observations for ahly-net.com
type: project
---

Portal: https://www.ahly-net.com/NBE/

Login form selectors (ASP.NET WebForms ID pattern):
- Username: `#ContentPlaceHolder1_Login1_UserName`
- Password: `#ContentPlaceHolder1_Login1_Password`
- Submit:   `#ContentPlaceHolder1_Login1_LoginButton`

Post-login dashboard confirmation element: `#ContentPlaceHolder1_GridView_AccSummary` (GridView table).

Transaction table ID pattern: `ContentPlaceHolder1_GridView_TransactionList`.
Navigate to it via `a[href*='AccountStatement']`.

Date format: `DD/MM/YYYY` (primary). Occasionally `DD-MM-YYYY`.

Amount format: comma thousands-separator, two decimal places (e.g. `12,345.67`). No currency prefix in amount cell.

Column layout (transaction table): Date | Value Date | Description | Debit | Credit | Balance

Debit/credit: separate columns. Empty cell = zero for that direction.

Login error indicator: `.failureNotification` element (ASP.NET standard).

**Why:** Captured during M2 implementation to avoid re-discovering selectors in future sessions.
**How to apply:** Use these selectors when maintaining or debugging `apps/api/app/scrapers/nbe.py`.
