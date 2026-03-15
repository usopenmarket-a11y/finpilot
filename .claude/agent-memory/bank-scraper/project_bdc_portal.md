---
name: BDC portal notes
description: Login selectors, date format, amount parsing, and table structure for ibanking.bdcbank.com.eg
type: project
---

Login URL: `https://ibanking.bdcbank.com.eg/`

Portal type: ASP.NET WebForms — similar structure to NBE (ContentPlaceHolder IDs, GridView tables).

**Login flow:**
- Username field: `input[id*='UserName']` or XPath fallback on `@id` / `@placeholder`.
- Password field: `input[type='password']`.
- Submit: `input[type='submit']` or `input[id*='LoginButton']`.
- Bad-credentials indicator: `.failureNotification` or `[class*='FailureText']` (same class names as NBE).
- Dashboard confirmation: `table[id*='AccSummary']` or `[class*='accountSummary']`.

**Date formats:**
- Primary: `DD/MM/YYYY`
- Secondary: `DD-MM-YYYY`
- Parser: `_parse_bdc_date` — tries `strptime` with both formats, falls back to permissive `re.split(r"[/\-]")`.

**Amount format:**
- Comma thousands-separators: `12,345.67`
- May be prefixed/suffixed with Arabic or Latin "EGP" text.
- `_parse_amount` strips Latin + Arabic letters via `re.sub(r"[A-Za-z\u0600-\u06FF]", "", ...)` before Decimal conversion.

**Transaction table:**
- Located by ID pattern `TransactionList` or class `transaction`/`statement`.
- Fallback: scan all tables for presence of Arabic "مدين"/"دائن" alongside "debit"/"credit" in header text.
- Column resolution: same `_resolve_txn_columns` pattern as NBE/CIB, extended with Arabic column labels `تاريخ`, `بيان`, `مدين`, `دائن`, `رصيد`.

**Modal handling:** A session-warning or announcement modal may appear post-login; dismissed via `.modal .close` or `[data-dismiss='modal']`.

**Why:** Documented during M3 scraper implementation (2026-03-16).
**How to apply:** Use these notes to accelerate selector debugging or when the portal structure changes.
