---
name: Scraper Architecture Decisions
description: Key design choices made during M2 scraper implementation that future work must respect
type: project
---

## Credential handling
Scrapers receive plaintext `username`/`password` strings — decryption is the router's responsibility, not the scraper's. The scraper stores them as `self._username` / `self._password` and deletes local copies in `finally` blocks after use. Never log them; always use `***`.

## ScraperResult sentinel UUIDs
`Transaction.id`, `user_id`, `account_id` and `BankAccount.id`, `user_id` are all set to `UUID("00000000-0000-0000-0000-000000000000")` by the scraper. The pipeline layer replaces these with real DB-assigned values before persisting.

## External ID / deduplication key
Format: `SHA-256("{date_iso}|{description[:40]}|{amount}")[:24]` — first 24 hex characters. Stable across repeated scrapes of the same row. Matches the `(account_id, external_id)` UNIQUE constraint on `public.transactions`.

## Selector resilience pattern
Every UI element: try CSS selector first (30 s), fall back to XPath (15 s). Document both selectors in comments. Raise `ScraperTimeoutError` only when both fail.

## Screenshot policy
`_safe_screenshot` is called ONLY on post-authentication pages (never on login forms). Written to `/tmp/finpilot_debug/` which is ephemeral.

## Anti-detection measures applied
- `navigator.webdriver = undefined` via `add_init_script`
- `--disable-blink-features=AutomationControlled` launch flag
- Randomised viewport: 1280–1920 × 800–1080
- Random Chrome user-agent from a pool of four strings
- `_type_human`: character-by-character typing with 80–180 ms per keystroke
- `_random_delay`: 2–5 s between major navigation events

## ScraperResult — multi-account shape (updated 2026-03-17)

`ScraperResult.accounts` is now `list[BankAccount]` (was a single `account`). The `.account` property on `ScraperResult` is a backward-compat shim that returns `accounts[0]`.

All single-account scrapers (CIB, BDC, UB) construct `ScraperResult(accounts=[account], ...)`.

NBE constructs `ScraperResult(accounts=accounts, ...)` where `accounts` may have 4 entries.

## Transaction routing in multi-account results

Each `Transaction.raw_data["account_number_masked"]` carries the masked number of the account it came from. The pipeline runner (`runner.py`) uses this to route each transaction to the correct DB `account_id` after per-account upsert. If no routing key is present AND there is only one account in the result, all transactions fall through to that single account (backward-compat fallback).

## Pipeline runner — multi-account loop

`run_pipeline()` loops over `result.accounts`, upserts each account independently, filters its transactions by `raw_data["account_number_masked"]`, deduplicates, and inserts. `PipelineRunResult` reports the primary (first) account and aggregated transaction counts.

**Why:** Documented to ensure new bank scrapers (BDC, UB) follow the same patterns without re-deriving them.
**How to apply:** When implementing `bdc.py` and `ub.py`, copy the same base structure and import from `app.scrapers.base`. Single-account scrapers: wrap account in a list. Multi-account scrapers: pass the full list and tag each Transaction.raw_data with account_number_masked.

## Render OOM mitigation (added 2026-06-13) — resource blocking + raw_html truncation

A full NBE 3-phase sync (accounts + CC + certificates) was getting OOM-killed on Render's 512MB instance during the CC phase (~460MB reached within ~3 min, before accounts/certificates even started). Root cause investigation (see job `4af8e826` on `srv-d6s0bg6a2pns73dfbdl0`, 2026-06-13 17:54-17:57): the single page is reused across all phases and re-renders the full Oracle JET/OBDX SPA (images, web fonts, CSS-heavy "flip card" widgets) at every navigation, and `ScraperResult.raw_html` accumulated up to 7 full `page.content()` dumps (dashboard, credit_cards, transactions_0..3, certificates) simultaneously.

Two fixes applied:
1. **`base.py` `_launch_browser`**: registered `context.route("**/*", _block_heavy_resources)` which aborts `image`, `media`, `font`, `stylesheet` requests context-wide (document/script/xhr/fetch pass through). Applies to ALL bank scrapers automatically since they share `_launch_browser`. This is the primary lever — banking SPA dashboards are very image/font/CSS heavy and none of that is needed for scraping.
2. **`nbe.py`**: added `_truncate_html()` (caps at `_RAW_HTML_MAX_CHARS = 20_000`) and wrapped all 10 `raw_html[...] = await page.content()` assignments across `scrape()`, `scrape_accounts()`, `scrape_credit_cards()`, `scrape_certificates()`. `raw_html` is debugging-only (not consumed by pipeline — verified via grep), so truncation is safe; existing tests only assert key presence/non-emptiness.

**Why:** 512MB Render free-tier ceiling; full sync never reached accounts/certificates phases before being killed.
**How to apply:** If other banks (CIB/BDC/UB/BDC-retail) get similar OOM reports, they automatically benefit from the `base.py` route-blocking fix already. If `raw_html` grows for those scrapers too, apply the same `_truncate_html` pattern (currently only defined in `nbe.py` — consider promoting to `base.py` if a second scraper needs it). If resource blocking alone isn't enough, the recommended next step (flagged to orchestrator, out of scraper-agent scope) is splitting the combined full-sync into sequential `scrape_accounts()` / `scrape_credit_cards()` / `scrape_certificates()` calls from the frontend — each launches its own browser with a clean memory baseline, trading time for memory headroom.

## Known pre-existing hang: test_scrapers.py

`app/tests/test_scrapers.py::TestNbeScraperScrape::test_happy_path_returns_scraper_result` hangs indefinitely (times out, exit 143) both in isolation and as part of the full `test_scrapers.py` suite. Reproduced with `timeout 30/100 pytest ...` both on plain `main` (via `git stash`) and with the 2026-06-13 OOM-mitigation changes (context.route + raw_html truncation) applied — the hang predates and is unaffected by that change. Likely an async mock/await mismatch in the test or `app.scrapers.base.async_playwright` patching, not investigated further (out of scope — owned by scraper/QA agents to fix). Use `--ignore=app/tests/test_scrapers.py --ignore=app/tests/test_scrapers_bdc_ub.py` (the latter also hangs the same way) when running the broader suite.
