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

**Why:** Documented to ensure new bank scrapers (BDC, UB) follow the same patterns without re-deriving them.
**How to apply:** When implementing `bdc.py` and `ub.py`, copy the same base structure and import from `app.scrapers.base`.
