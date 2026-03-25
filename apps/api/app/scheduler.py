"""Daily auto-sync scheduler.

Runs once per day at a random time between 08:00–09:00 Cairo time (EET, UTC+2),
which corresponds to 06:00–07:00 UTC.  Syncs all users' active bank credentials
sequentially to respect the single-Playwright-instance constraint on Render's
free tier.

Uses APScheduler AsyncIOScheduler so the job fires inside the existing FastAPI
event loop without spawning additional threads or processes.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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

    def _fetch_credentials() -> list[dict]:
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
        bank: str = cred["bank"]

        # If another sync is running (e.g. a manual user-triggered sync), wait
        # up to 10 minutes before giving up on this credential.
        if _SCRAPE_SEMAPHORE.locked():
            logger.warning(
                "Daily auto-sync: semaphore locked for %s/%s, waiting up to 10 min",
                bank, credential_id,
            )
            for _ in range(120):
                await asyncio.sleep(5)
                if not _SCRAPE_SEMAPHORE.locked():
                    break
            else:
                logger.error(
                    "Daily auto-sync: timed out waiting for semaphore (%s/%s), skipping",
                    bank, credential_id,
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
                    bank, str(user_id)[-8:],
                )
            else:
                failed += 1
                logger.warning(
                    "Daily auto-sync: %s FAILED for user …%s — %s",
                    bank, str(user_id)[-8:], job.get("error"),
                )
        except Exception:
            failed += 1
            logger.exception(
                "Daily auto-sync: unexpected error for %s / credential %s",
                bank, credential_id,
            )

    logger.info(
        "Daily auto-sync: complete — %d succeeded, %d failed", synced, failed
    )


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    Fires daily at a random minute within the 06:xx UTC window
    (= 08:00–09:00 Cairo EET).  The minute is randomised once at startup so
    that restarts don't always fire at :00.
    """
    random_minute = random.randint(0, 59)
    logger.info(
        "Daily auto-sync scheduled for 06:%02d UTC (08:%02d Cairo EET) every day",
        random_minute,
        random_minute,
    )

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_daily_sync,
        trigger=CronTrigger(hour=6, minute=random_minute, timezone="UTC"),
        id="daily_auto_sync",
        name="Daily bank sync",
        replace_existing=True,
        # Allow up to 1 hour late — handles Render free tier instance sleep
        # during the scheduled window.
        misfire_grace_time=3600,
    )
    return scheduler
