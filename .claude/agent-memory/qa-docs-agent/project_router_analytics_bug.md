---
name: Analytics router stale import bug
description: app/routers/analytics.py imports `compute_trend_report` but the function is named `compute_trends` in app/analytics/trends.py — causes ImportError at app startup
type: project
---

`app/routers/analytics.py` line ~39 imports `compute_trend_report` from `app.analytics.trends`, but the correct public name is `compute_trends` (see `app/analytics/__init__.py` and `app/analytics/trends.py`).

**Why:** The router was written before the analytics module was finalised, or the function was renamed during analytics agent implementation without updating the router.

**How to apply:** When the Backend/Scraper/Analytics Agent touches `app/routers/analytics.py`, flag this as the first thing to fix. The one-line fix is: `from app.analytics.trends import compute_trends` (replacing `compute_trend_report`). Do not attempt to fix this yourself — the file is owned by the Backend Agent.
