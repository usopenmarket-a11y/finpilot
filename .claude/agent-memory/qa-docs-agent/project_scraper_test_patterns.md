---
name: Scraper test patterns
description: Mocking approach, selector discrimination, and fixture patterns for NBE/CIB scraper tests
type: project
---

Key patterns established in `apps/api/app/tests/test_scrapers.py`:

**Playwright mock chain**
`async_playwright` is patched at `app.scrapers.base.async_playwright`.
The mock is built as: `async_playwright()` returns a context manager whose
`.start()` returns `mock_pw`; `mock_pw.chromium.launch()` returns
`mock_browser`; `mock_browser.new_context()` returns `mock_context`;
`mock_context.new_page()` returns `mock_page`.
All of these are `AsyncMock`. `_build_mock_playwright()` helper in the test
file encapsulates this entire chain.

**Error-selector discrimination (critical pattern)**
`_wait_for_dashboard` in both NBE and CIB calls `page.query_selector` with the
login-error CSS selector first. If any element is returned it raises
`ScraperLoginError`. Happy-path tests must therefore return `None` for error
selectors and a real `AsyncMock` element for all other selectors. Use a
discriminating async function as `mock_page.query_selector`:

```python
_ERROR_SELECTORS = {".failureNotification", "xpath=//*[contains(@class,'failureNotification')]"}
async def _query_selector_nbe(selector: str) -> Any:
    return None if selector in _ERROR_SELECTORS else mock_element
mock_page.query_selector = _query_selector_nbe
```

CIB error selectors: `".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"`
and its xpath variant.

**page.content() side_effect count for happy-path tests**
NBE scrape(): 4 content() calls needed:
1. raw_html["dashboard"]
2. _extract_account -> page.content()
3. raw_html["transactions"]
4. _extract_transactions -> page.content()

CIB scrape(): 4 content() calls needed (same pattern).

**Module-level helpers are directly importable and testable**
`_parse_nbe_date`, `_parse_amount`, `_make_external_id`, `_normalise_account_type`,
`_normalise_currency`, `_resolve_txn_columns`, `_parse_transaction_row` from
`app.scrapers.nbe` — same pattern for CIB.  No scraper instantiation needed.

**`datetime.utcnow()` DeprecationWarnings**
Source files `nbe.py` and `cib.py` use `datetime.utcnow()` which emits
DeprecationWarning under Python 3.12. These are in source files owned by the
Scraper Agent — not in test files — so they appear as warnings not failures.
Notify Scraper Agent to switch to `datetime.now(datetime.UTC)`.

**Why:** Established for M2 scraper test suite.
**How to apply:** Reuse `_build_mock_playwright()` and the error-selector
discrimination pattern for any future scraper (BDC, UB).
