"""Daily auto-sync scheduler.

Strategy
--------
Render's free tier suspends the process after ~15 minutes of inactivity.
A fixed-time cron job (e.g. "fire at 06:07 UTC") is therefore unreliable —
the instance is almost always asleep at that moment, and APScheduler only
fires a misfired job while the *scheduler is running*, not when it first
starts.

Instead we use two complementary mechanisms:

1. **Startup check** — on every cold start, check whether today's sync has
   already run (by reading the most recent ``last_synced_at`` across all
   credentials).  If not, schedule a one-shot job to fire after a short
   randomised delay (10–60 s) so the startup HTTP response is not blocked.

2. **Long-running fallback cron** — a daily cron job at 06:xx UTC covers
   the edge case where the instance stays alive across midnight (e.g. if
   the user keeps pinging it).  ``next_run_time=None`` disables the
   catch-up-on-missed-fires behaviour; the startup check already handles
   that.

Sequencing
----------
Credentials are synced one at a time to respect the single-Playwright-
instance constraint on Render's free tier (512 MB RAM).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from supabase import create_client

from app.config import settings

logger = logging.getLogger(__name__)


async def _run_daily_sync() -> None:
    """Fetch all active credentials and sync them one at a time.

    Sequential execution ensures only one Playwright browser instance runs
    at a time, which is required on Render's free tier (512 MB RAM).
    Per-credential errors are logged but do not abort the remaining syncs.
    """
    # Import here to avoid circular imports at module load time.
    from app.routers.sync import _JOBS, _SCRAPE_SEMAPHORE, _background_sync_task  # noqa: PLC0415

    logger.info("Daily auto-sync: starting at %s UTC", datetime.now(UTC).isoformat())

    def _fetch_credentials() -> list[Any]:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        resp = (
            client.table("bank_credentials")
            .select("id, user_id, bank")
            .eq("is_active", True)
            .execute()
        )
        return resp.data or []

    try:
        credentials = await asyncio.to_thread(_fetch_credentials)
    except Exception:
        logger.exception("Daily auto-sync: failed to fetch credentials, aborting")
        return

    if not credentials:
        logger.info("Daily auto-sync: no active credentials found, nothing to do")
        return

    logger.info("Daily auto-sync: %d credential(s) to process", len(credentials))

    synced = 0
    failed = 0

    for cred in credentials:
        credential_id: str = cred["id"]
        user_id = UUID(cred["user_id"])
        bank: Literal["NBE", "CIB", "BDC", "BDC_RETAIL", "UB"] = cred["bank"]

        # If another sync is running (e.g. a manual user-triggered sync), wait
        # up to 10 minutes before giving up on this credential.
        if _SCRAPE_SEMAPHORE.locked():
            logger.warning(
                "Daily auto-sync: semaphore locked for %s/%s, waiting up to 10 min",
                bank,
                credential_id,
            )
            for _ in range(120):
                await asyncio.sleep(5)
                if not _SCRAPE_SEMAPHORE.locked():
                    break
            else:
                logger.error(
                    "Daily auto-sync: timed out waiting for semaphore (%s/%s), skipping",
                    bank,
                    credential_id,
                )
                failed += 1
                continue

        job_id = f"auto-{uuid4()}"
        _JOBS[job_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "finished_at": None,
            "user_id": str(user_id),
            "bank": bank,
            "credential_id": credential_id,
        }

        try:
            await _background_sync_task(job_id, user_id, bank, credential_id)
            job = _JOBS.get(job_id, {})
            if job.get("status") == "complete":
                synced += 1
                logger.info(
                    "Daily auto-sync: %s OK for user …%s",
                    bank,
                    str(user_id)[-8:],
                )
            else:
                failed += 1
                logger.warning(
                    "Daily auto-sync: %s FAILED for user …%s — %s",
                    bank,
                    str(user_id)[-8:],
                    job.get("error"),
                )
        except Exception:
            failed += 1
            logger.exception(
                "Daily auto-sync: unexpected error for %s / credential %s",
                bank,
                credential_id,
            )

    logger.info("Daily auto-sync: complete — %d succeeded, %d failed", synced, failed)


async def _needs_sync_today() -> bool:
    """Return True if no credential has been synced today (UTC date).

    Reads the most recent ``last_synced_at`` across all active credentials.
    Returns True when that value is either absent or from a previous day,
    meaning today's sync window has not yet run.
    """
    today = date.today()

    def _fetch() -> list[Any]:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        resp = (
            client.table("bank_credentials")
            .select("last_synced_at")
            .eq("is_active", True)
            .order("last_synced_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data or []

    try:
        rows = await asyncio.to_thread(_fetch)
    except Exception:
        logger.exception("Startup sync check: failed to query credentials")
        return False

    if not rows:
        logger.info("Startup sync check: no active credentials found")
        return False

    last_synced_raw: str | None = rows[0].get("last_synced_at")
    if not last_synced_raw:
        logger.info("Startup sync check: credentials exist but never synced — will sync now")
        return True

    last_synced_date = datetime.fromisoformat(last_synced_raw.replace("Z", "+00:00")).date()
    needs = last_synced_date < today
    logger.info(
        "Startup sync check: last_synced=%s today=%s needs_sync=%s",
        last_synced_date,
        today,
        needs,
    )
    return needs


async def _startup_sync_if_needed() -> None:
    """Run today's sync if it hasn't happened yet.

    Called via a one-shot DateTrigger a few seconds after startup so that
    the HTTP server is fully ready before Playwright launches.
    """
    if await _needs_sync_today():
        logger.info("Startup sync: today's sync has not run yet — starting now")
        await _run_daily_sync()
    else:
        logger.info("Startup sync: already synced today — skipping")


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    Two jobs are registered:

    * **startup_sync_check** — fires once, 15–45 s after startup.  Checks
      whether today's sync has already run; runs it if not.  This is the
      primary mechanism for Render free-tier instances that sleep between
      requests.

    * **daily_auto_sync** — a daily cron at 06:xx UTC as a belt-and-
      suspenders fallback for long-running instances.  ``next_run_time=None``
      prevents APScheduler from immediately firing a "missed" job on startup
      (the startup check already handles that case).
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    # One-shot startup check — fires 15–45 s after the server is ready
    startup_delay_s = random.randint(15, 45)
    startup_run_at = datetime.now(UTC) + timedelta(seconds=startup_delay_s)
    scheduler.add_job(
        _startup_sync_if_needed,
        trigger=DateTrigger(run_date=startup_run_at),
        id="startup_sync_check",
        name="Startup sync check",
        replace_existing=True,
    )
    logger.info("Startup sync check scheduled to fire in ~%d s", startup_delay_s)

    # Daily fallback cron — for long-running instances; next_run_time=None
    # disables catch-up so it doesn't double-fire alongside the startup check.
    random_minute = random.randint(0, 59)
    scheduler.add_job(
        _run_daily_sync,
        trigger=CronTrigger(hour=6, minute=random_minute, timezone="UTC"),
        id="daily_auto_sync",
        name="Daily bank sync (cron fallback)",
        replace_existing=True,
        next_run_time=None,  # don't fire immediately on startup
    )
    logger.info(
        "Daily cron fallback scheduled for 06:%02d UTC (08:%02d Cairo EET)",
        random_minute,
        random_minute,
    )

    return scheduler
