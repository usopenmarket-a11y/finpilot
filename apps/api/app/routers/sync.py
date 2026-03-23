"""Sync router — trigger a bank sync using stored credentials.

Async Job Pattern
-----------------
Due to Cloudflare's 100-second HTTP timeout and NBE scraper taking 2-4 minutes,
syncs are implemented as background async tasks:

1. POST /accounts/sync/{bank} validates credentials exist, starts a background
   task, and returns HTTP 202 with a job_id immediately.
2. GET /accounts/sync/status/{job_id} returns the job status and result
   (once complete).

Job state is stored in an in-memory dict (safe for Render free tier single instance).

Security contract
-----------------
* Credentials are read from Supabase (encrypted at rest) and decrypted
  in-memory only for the duration of the scrape.  They are never returned
  in any response payload.
* ``user_id`` is taken from the ``x-user-id`` header and validated as a UUID.
* Decrypted credential strings (username / password) are ``del``-ed
  immediately after the scraper call, before any awaiting or branching.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from supabase import create_client

from app.config import settings
from app.crypto import CryptoError, decrypt
from app.pipeline.runner import run_pipeline
from app.scrapers import (
    BankPortalUnreachableError,
    BDCScraper,
    CIBScraper,
    NBEScraper,
    ScraperLoginError,
    ScraperParseError,
    ScraperTimeoutError,
    UBScraper,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sync"])

_SCRAPER_MAP = {
    "NBE": NBEScraper,
    "CIB": CIBScraper,
    "BDC": BDCScraper,
    "UB": UBScraper,
}

_VALID_BANKS = frozenset(_SCRAPER_MAP.keys())

# In-memory job state storage. Keyed by job_id (UUID string).
_JOBS: dict[str, dict[str, Any]] = {}

# Global scrape semaphore — only one Playwright browser at a time on the
# Render free tier (512 MB RAM).  A second request while one is running
# gets a 429 so the client can retry rather than crashing the instance.
_SCRAPE_SEMAPHORE = asyncio.Semaphore(1)

# ---------------------------------------------------------------------------
# Render free-tier keepalive
# ---------------------------------------------------------------------------
# Render free-tier suspends the instance after ~1 minute of no inbound HTTP
# traffic, killing any running asyncio background tasks.  This keepalive task
# self-pings the health endpoint every 30 seconds while a job is active so
# the instance stays alive for the full scraper duration (~3-4 minutes).

_KEEPALIVE_INTERVAL_S = 30
# Use the public external URL so Render counts this as inbound traffic and
# does not suspend the free-tier instance while the scraper is running.
# Localhost pings do NOT count as external traffic for Render's suspension logic.
_HEALTH_URL = "https://finpilot-api-lrfg.onrender.com/api/v1/health"


async def _keepalive_while_running(job_id: str) -> None:
    """Ping the external health endpoint every 30s until the job is no longer running.

    The first ping fires immediately (before the sleep) so even jobs that
    complete or are killed in the first 30s window still trigger a keepalive.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            job = _JOBS.get(job_id)
            if job is None or job["status"] not in ("pending", "running"):
                break
            try:
                await client.get(_HEALTH_URL)
            except Exception:
                pass  # non-fatal — just keep going
            await asyncio.sleep(_KEEPALIVE_INTERVAL_S)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SyncResponse(BaseModel):
    """Result of a completed sync."""

    bank: str
    account_number_masked: str
    transactions_scraped: int
    transactions_saved: int
    synced_at: str


class SyncJobStartResponse(BaseModel):
    """Response to POST /accounts/sync/{bank} — job started."""

    job_id: str = Field(description="UUID string to poll status with")
    status: str = Field(default="pending", description="Initial job status")


class SyncJobStatusResponse(BaseModel):
    """Response to GET /accounts/sync/status/{job_id}."""

    job_id: str = Field(description="UUID string")
    status: str = Field(description="'pending', 'running', 'complete', or 'failed'")
    result: SyncResponse | None = Field(
        default=None, description="Populated when status='complete'"
    )
    error: str | None = Field(default=None, description="Populated when status='failed'")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_user_id(raw: str | None) -> UUID:
    """Parse and validate x-user-id header."""
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-user-id header is required",
        )
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-user-id header must be a valid UUID",
        )


async def _background_sync_task(
    job_id: str,
    user_id: UUID,
    bank: Literal["NBE", "CIB", "BDC", "UB"],
) -> None:
    """Background task that performs the scrape + pipeline without blocking HTTP."""
    _JOBS[job_id]["status"] = "running"

    try:
        # ------------------------------------------------------------------
        # Step 1 — fetch stored encrypted credentials from Supabase.
        # ------------------------------------------------------------------
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        try:
            response = (
                client.table("bank_credentials")
                .select("encrypted_username, encrypted_password")
                .eq("user_id", str(user_id))
                .eq("bank", bank)
                .eq("is_active", True)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to retrieve stored credentials"
            return

        if not response.data:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = f"No active credentials found for bank {bank}"
            return

        row = response.data
        assert isinstance(row, dict)
        enc_username: str = row["encrypted_username"]
        enc_password: str = row["encrypted_password"]

        # ------------------------------------------------------------------
        # Step 2 — decrypt credentials.
        # These variables must never appear in any log call.
        # ------------------------------------------------------------------
        username: str | None = None
        password: str | None = None
        try:
            username = decrypt(enc_username, settings.encryption_key)
            password = decrypt(enc_password, settings.encryption_key)
        except CryptoError:
            logger.warning("Stored credential token is malformed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token is malformed"
            return
        except ValueError:
            logger.warning("Stored credential token authentication failed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token could not be authenticated"
            return

        # ------------------------------------------------------------------
        # Step 3 — run the scraper (serialised via global semaphore so the
        # Render free-tier 512 MB instance never runs two Playwright browsers
        # concurrently).
        # ------------------------------------------------------------------
        result = None
        try:
            assert username is not None and password is not None
            scraper_class = _SCRAPER_MAP[bank]
            scraper = scraper_class(username=username, password=password)  # type: ignore[abstract]

            logger.info("Sync initiated via stored credentials", extra={"bank": bank})
            async with _SCRAPE_SEMAPHORE:
                result = await scraper.scrape()
        except ScraperLoginError:
            logger.warning("Sync failed: bank rejected credentials", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Invalid bank credentials"
            return
        except ScraperTimeoutError:
            logger.warning("Sync failed: portal timed out", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal timed out"
            return
        except ScraperParseError:
            logger.warning("Sync failed: could not parse portal response", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to parse bank portal response"
            return
        except BankPortalUnreachableError:
            logger.warning("Sync failed: portal unreachable", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal unreachable"
            return
        except Exception as exc:
            logger.error("Sync failed: unexpected error", extra={"bank": bank}, exc_info=exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper error"
            return
        finally:
            # Always delete plaintext credentials from memory
            if username is not None:
                del username
            if password is not None:
                del password

        # Verify scraper succeeded and produced a result
        if result is None:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper returned no result"
            return

        # ------------------------------------------------------------------
        # Step 4 — run the ETL pipeline.
        # ------------------------------------------------------------------
        transactions_saved = 0
        try:
            from supabase import acreate_client

            pipeline_client = await acreate_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            pipeline_result = await run_pipeline(
                result, user_id=user_id, supabase_client=pipeline_client
            )
            transactions_saved = pipeline_result.transactions_new
        except Exception as exc:
            logger.warning(
                "Pipeline failed during sync (scrape succeeded): %s", exc, extra={"bank": bank}
            )

        # ------------------------------------------------------------------
        # Step 5 — update last_synced_at (non-fatal).
        # ------------------------------------------------------------------
        now_iso = datetime.now(UTC).isoformat()
        try:
            update_client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            update_client.table("bank_credentials").update({"last_synced_at": now_iso}).eq(
                "user_id", str(user_id)
            ).eq("bank", bank).execute()
        except Exception:
            pass  # non-fatal

        transactions_scraped = len(result.transactions)
        # Summarise across all accounts — use the primary (first) account for the
        # masked number reported to the caller.  All accounts share the same bank_name.
        primary_account = result.accounts[0]
        accounts_scraped = len(result.accounts)
        logger.info(
            "Sync completed",
            extra={
                "bank": bank,
                "accounts_scraped": accounts_scraped,
                "account_number_masked": primary_account.account_number_masked,
                "transactions_scraped": transactions_scraped,
                "transactions_saved": transactions_saved,
            },
        )

        # Store the result in the job state.
        sync_response = SyncResponse(
            bank=primary_account.bank_name,
            account_number_masked=primary_account.account_number_masked,
            transactions_scraped=transactions_scraped,
            transactions_saved=transactions_saved,
            synced_at=now_iso,
        )
        _JOBS[job_id]["status"] = "complete"
        _JOBS[job_id]["result"] = sync_response

    except Exception as exc:
        logger.error("Background sync task failed unexpectedly", exc_info=exc)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["error"] = "Unexpected error during sync"


# ---------------------------------------------------------------------------
# Focused background sync tasks (NBE split-sync)
# ---------------------------------------------------------------------------


async def _background_sync_accounts_task(
    job_id: str,
    user_id: UUID,
    bank: Literal["NBE", "CIB", "BDC", "UB"],
) -> None:
    """Background task: scrape demand-deposit accounts + transactions only."""
    _JOBS[job_id]["status"] = "running"

    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        try:
            response = (
                client.table("bank_credentials")
                .select("encrypted_username, encrypted_password")
                .eq("user_id", str(user_id))
                .eq("bank", bank)
                .eq("is_active", True)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to retrieve stored credentials"
            return

        if not response.data:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = f"No active credentials found for bank {bank}"
            return

        row = response.data
        assert isinstance(row, dict)
        enc_username: str = row["encrypted_username"]
        enc_password: str = row["encrypted_password"]

        username: str | None = None
        password: str | None = None
        try:
            username = decrypt(enc_username, settings.encryption_key)
            password = decrypt(enc_password, settings.encryption_key)
        except CryptoError:
            logger.warning("Stored credential token is malformed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token is malformed"
            return
        except ValueError:
            logger.warning("Stored credential token authentication failed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token could not be authenticated"
            return

        result = None
        try:
            assert username is not None and password is not None
            scraper_class = _SCRAPER_MAP[bank]
            scraper = scraper_class(username=username, password=password)  # type: ignore[abstract]
            logger.info("Accounts-only sync initiated via stored credentials", extra={"bank": bank})
            async with _SCRAPE_SEMAPHORE:
                if bank == "NBE":
                    assert isinstance(scraper, NBEScraper)
                    result = await scraper.scrape_accounts()
                else:
                    result = await scraper.scrape()
        except ScraperLoginError:
            logger.warning("Accounts sync failed: bank rejected credentials", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Invalid bank credentials"
            return
        except ScraperTimeoutError:
            logger.warning("Accounts sync failed: portal timed out", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal timed out"
            return
        except ScraperParseError:
            logger.warning(
                "Accounts sync failed: could not parse portal response", extra={"bank": bank}
            )
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to parse bank portal response"
            return
        except BankPortalUnreachableError:
            logger.warning("Accounts sync failed: portal unreachable", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal unreachable"
            return
        except Exception as exc:
            logger.error(
                "Accounts sync failed: unexpected error", extra={"bank": bank}, exc_info=exc
            )
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper error"
            return
        finally:
            if username is not None:
                del username
            if password is not None:
                del password

        if result is None:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper returned no result"
            return

        transactions_saved = 0
        try:
            from supabase import acreate_client

            pipeline_client = await acreate_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            pipeline_result = await run_pipeline(
                result, user_id=user_id, supabase_client=pipeline_client
            )
            transactions_saved = pipeline_result.transactions_new
        except Exception as exc:
            logger.warning(
                "Pipeline failed during accounts sync (scrape succeeded): %s",
                exc,
                extra={"bank": bank},
            )

        now_iso = datetime.now(UTC).isoformat()
        try:
            update_client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            update_client.table("bank_credentials").update({"last_synced_at": now_iso}).eq(
                "user_id", str(user_id)
            ).eq("bank", bank).execute()
        except Exception:
            pass

        transactions_scraped = len(result.transactions)
        primary_account = result.accounts[0]
        accounts_scraped = len(result.accounts)
        logger.info(
            "Accounts sync completed",
            extra={
                "bank": bank,
                "accounts_scraped": accounts_scraped,
                "account_number_masked": primary_account.account_number_masked,
                "transactions_scraped": transactions_scraped,
                "transactions_saved": transactions_saved,
            },
        )

        sync_response = SyncResponse(
            bank=primary_account.bank_name,
            account_number_masked=primary_account.account_number_masked,
            transactions_scraped=transactions_scraped,
            transactions_saved=transactions_saved,
            synced_at=now_iso,
        )
        _JOBS[job_id]["status"] = "complete"
        _JOBS[job_id]["result"] = sync_response

    except Exception as exc:
        logger.error("Background accounts sync task failed unexpectedly", exc_info=exc)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["error"] = "Unexpected error during sync"


async def _background_sync_cc_task(
    job_id: str,
    user_id: UUID,
    bank: Literal["NBE", "CIB", "BDC", "UB"],
) -> None:
    """Background task: scrape credit card accounts + statement transactions only."""
    _JOBS[job_id]["status"] = "running"

    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        try:
            response = (
                client.table("bank_credentials")
                .select("encrypted_username, encrypted_password")
                .eq("user_id", str(user_id))
                .eq("bank", bank)
                .eq("is_active", True)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to retrieve stored credentials"
            return

        if not response.data:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = f"No active credentials found for bank {bank}"
            return

        row = response.data
        assert isinstance(row, dict)
        enc_username = row["encrypted_username"]
        enc_password = row["encrypted_password"]

        username: str | None = None
        password: str | None = None
        try:
            username = decrypt(enc_username, settings.encryption_key)
            password = decrypt(enc_password, settings.encryption_key)
        except CryptoError:
            logger.warning("Stored credential token is malformed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token is malformed"
            return
        except ValueError:
            logger.warning("Stored credential token authentication failed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token could not be authenticated"
            return

        result = None
        try:
            assert username is not None and password is not None
            scraper_class = _SCRAPER_MAP[bank]
            scraper = scraper_class(username=username, password=password)  # type: ignore[abstract]
            logger.info("CC-only sync initiated via stored credentials", extra={"bank": bank})
            async with _SCRAPE_SEMAPHORE:
                if bank == "NBE":
                    assert isinstance(scraper, NBEScraper)
                    result = await scraper.scrape_credit_cards()
                else:
                    result = await scraper.scrape()
        except ScraperLoginError:
            logger.warning("CC sync failed: bank rejected credentials", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Invalid bank credentials"
            return
        except ScraperTimeoutError:
            logger.warning("CC sync failed: portal timed out", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal timed out"
            return
        except ScraperParseError:
            logger.warning("CC sync failed: could not parse portal response", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to parse bank portal response"
            return
        except BankPortalUnreachableError:
            logger.warning("CC sync failed: portal unreachable", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal unreachable"
            return
        except Exception as exc:
            logger.error("CC sync failed: unexpected error", extra={"bank": bank}, exc_info=exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper error"
            return
        finally:
            if username is not None:
                del username
            if password is not None:
                del password

        if result is None:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper returned no result"
            return

        transactions_saved = 0
        try:
            from supabase import acreate_client

            pipeline_client = await acreate_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            pipeline_result = await run_pipeline(
                result, user_id=user_id, supabase_client=pipeline_client
            )
            transactions_saved = pipeline_result.transactions_new
        except Exception as exc:
            logger.warning(
                "Pipeline failed during CC sync (scrape succeeded): %s",
                exc,
                extra={"bank": bank},
            )

        now_iso = datetime.now(UTC).isoformat()
        try:
            update_client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            update_client.table("bank_credentials").update({"last_synced_at": now_iso}).eq(
                "user_id", str(user_id)
            ).eq("bank", bank).execute()
        except Exception:
            pass

        transactions_scraped = len(result.transactions)
        if not result.accounts:
            _JOBS[job_id]["status"] = "complete"
            _JOBS[job_id]["result"] = SyncResponse(
                bank=bank,
                account_number_masked="****",
                transactions_scraped=transactions_scraped,
                transactions_saved=transactions_saved,
                synced_at=now_iso,
            )
            return

        primary_account = result.accounts[0]
        accounts_scraped = len(result.accounts)
        logger.info(
            "CC sync completed",
            extra={
                "bank": bank,
                "accounts_scraped": accounts_scraped,
                "account_number_masked": primary_account.account_number_masked,
                "transactions_scraped": transactions_scraped,
                "transactions_saved": transactions_saved,
            },
        )

        _JOBS[job_id]["status"] = "complete"
        _JOBS[job_id]["result"] = SyncResponse(
            bank=primary_account.bank_name,
            account_number_masked=primary_account.account_number_masked,
            transactions_scraped=transactions_scraped,
            transactions_saved=transactions_saved,
            synced_at=now_iso,
        )

    except Exception as exc:
        logger.error("Background CC sync task failed unexpectedly", exc_info=exc)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["error"] = "Unexpected error during sync"


async def _background_sync_certificates_task(
    job_id: str,
    user_id: UUID,
    bank: Literal["NBE", "CIB", "BDC", "UB"],
) -> None:
    """Background task: scrape certificate/term-deposit accounts only."""
    _JOBS[job_id]["status"] = "running"

    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        try:
            response = (
                client.table("bank_credentials")
                .select("encrypted_username, encrypted_password")
                .eq("user_id", str(user_id))
                .eq("bank", bank)
                .eq("is_active", True)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to retrieve stored credentials"
            return

        if not response.data:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = f"No active credentials found for bank {bank}"
            return

        row = response.data
        assert isinstance(row, dict)
        enc_username = row["encrypted_username"]
        enc_password = row["encrypted_password"]

        username: str | None = None
        password: str | None = None
        try:
            username = decrypt(enc_username, settings.encryption_key)
            password = decrypt(enc_password, settings.encryption_key)
        except CryptoError:
            logger.warning("Stored credential token is malformed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token is malformed"
            return
        except ValueError:
            logger.warning("Stored credential token authentication failed for bank=%s", bank)
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Stored credential token could not be authenticated"
            return

        result = None
        try:
            assert username is not None and password is not None
            scraper_class = _SCRAPER_MAP[bank]
            scraper = scraper_class(username=username, password=password)  # type: ignore[abstract]
            logger.info(
                "Certificates-only sync initiated via stored credentials", extra={"bank": bank}
            )
            async with _SCRAPE_SEMAPHORE:
                if bank == "NBE":
                    assert isinstance(scraper, NBEScraper)
                    result = await scraper.scrape_certificates()
                else:
                    result = await scraper.scrape()
        except ScraperLoginError:
            logger.warning(
                "Certificates sync failed: bank rejected credentials", extra={"bank": bank}
            )
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Invalid bank credentials"
            return
        except ScraperTimeoutError:
            logger.warning("Certificates sync failed: portal timed out", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal timed out"
            return
        except ScraperParseError:
            logger.warning(
                "Certificates sync failed: could not parse portal response", extra={"bank": bank}
            )
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Failed to parse bank portal response"
            return
        except BankPortalUnreachableError:
            logger.warning("Certificates sync failed: portal unreachable", extra={"bank": bank})
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Bank portal unreachable"
            return
        except Exception as exc:
            logger.error(
                "Certificates sync failed: unexpected error", extra={"bank": bank}, exc_info=exc
            )
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper error"
            return
        finally:
            if username is not None:
                del username
            if password is not None:
                del password

        if result is None:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = "Scraper returned no result"
            return

        transactions_saved = 0
        try:
            from supabase import acreate_client

            pipeline_client = await acreate_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            pipeline_result = await run_pipeline(
                result, user_id=user_id, supabase_client=pipeline_client
            )
            transactions_saved = pipeline_result.transactions_new
        except Exception as exc:
            logger.warning(
                "Pipeline failed during certificates sync (scrape succeeded): %s",
                exc,
                extra={"bank": bank},
            )

        now_iso = datetime.now(UTC).isoformat()
        try:
            update_client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key.get_secret_value(),
            )
            update_client.table("bank_credentials").update({"last_synced_at": now_iso}).eq(
                "user_id", str(user_id)
            ).eq("bank", bank).execute()
        except Exception:
            pass

        transactions_scraped = len(result.transactions)
        if not result.accounts:
            _JOBS[job_id]["status"] = "complete"
            _JOBS[job_id]["result"] = SyncResponse(
                bank=bank,
                account_number_masked="****",
                transactions_scraped=transactions_scraped,
                transactions_saved=transactions_saved,
                synced_at=now_iso,
            )
            return

        primary_account = result.accounts[0]
        accounts_scraped = len(result.accounts)
        logger.info(
            "Certificates sync completed",
            extra={
                "bank": bank,
                "accounts_scraped": accounts_scraped,
                "account_number_masked": primary_account.account_number_masked,
                "transactions_scraped": transactions_scraped,
                "transactions_saved": transactions_saved,
            },
        )

        _JOBS[job_id]["status"] = "complete"
        _JOBS[job_id]["result"] = SyncResponse(
            bank=primary_account.bank_name,
            account_number_masked=primary_account.account_number_masked,
            transactions_scraped=transactions_scraped,
            transactions_saved=transactions_saved,
            synced_at=now_iso,
        )

    except Exception as exc:
        logger.error("Background certificates sync task failed unexpectedly", exc_info=exc)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["error"] = "Unexpected error during sync"


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/accounts/sync/{bank}",
    response_model=SyncJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a bank account sync job",
)
async def start_sync_job(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> SyncJobStartResponse:
    """Start a background sync job.

    Validates that credentials exist, then starts a background asyncio task
    to run the scraper and ETL pipeline. Returns immediately with a job_id
    to poll status.

    HTTP response
    -------------
    * 202 — job started successfully. Use job_id to poll /accounts/sync/status/{job_id}
    * 404 — no credentials stored for this bank / user combination.
    * 500 — failed to validate credentials.
    """
    user_id = _parse_user_id(x_user_id)

    # Validate that credentials exist (lightweight check before spawning task).
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    try:
        response = (
            client.table("bank_credentials")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("bank", bank)
            .eq("is_active", True)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve stored credentials",
        ) from exc

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active credentials found for bank {bank}",
        )

    # Reject if a scrape is already running — two concurrent Playwright
    # browsers exceed the Render free-tier 512 MB RAM limit and crash
    # the instance.
    if _SCRAPE_SEMAPHORE.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A sync is already in progress. Please wait and retry.",
        )

    # Create job and spawn background task.
    job_id = str(uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "user_id": str(user_id),
        "bank": bank,
    }

    # Schedule the background task and a keepalive without awaiting them.
    asyncio.create_task(_background_sync_task(job_id, user_id, bank))
    asyncio.create_task(_keepalive_while_running(job_id))

    return SyncJobStartResponse(job_id=job_id, status="pending")


@router.get(
    "/accounts/sync/status/{job_id}",
    response_model=SyncJobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll the status of a sync job",
)
async def get_sync_status(job_id: str) -> SyncJobStatusResponse:
    """Check the status of a sync job by ID.

    Returns the current job status and (if complete) the sync result or error.
    Clients should poll this endpoint every 5 seconds until status is 'complete'
    or 'failed' (max 5 minutes).

    HTTP response
    -------------
    * 200 — job found, returning status and (if complete) result/error.
    * 404 — job_id not found.
    """
    if job_id not in _JOBS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    job = _JOBS[job_id]
    return SyncJobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=job["result"],
        error=job["error"],
    )


def _validate_credentials_exist(
    user_id: UUID,
    bank: Literal["NBE", "CIB", "BDC", "UB"],
) -> None:
    """Raise HTTPException if no active credentials exist for the given user + bank.

    Shared pre-flight check used by all focused sync endpoints.
    """
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    try:
        response = (
            client.table("bank_credentials")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("bank", bank)
            .eq("is_active", True)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch credentials for bank=%s: %s", bank, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve stored credentials",
        ) from exc

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active credentials found for bank {bank}",
        )


@router.post(
    "/accounts/sync/{bank}/accounts",
    response_model=SyncJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a demand-deposit accounts-only sync job",
)
async def start_sync_accounts_job(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> SyncJobStartResponse:
    """Start a background sync that scrapes demand-deposit accounts and transactions only.

    For NBE this calls ``scraper.scrape_accounts()`` instead of the full
    ``scraper.scrape()``, skipping CC and certificate scraping for a faster run.
    For all other banks the full ``scrape()`` is used as a fallback.

    HTTP response
    -------------
    * 202 — job started. Poll /accounts/sync/status/{job_id} for results.
    * 404 — no credentials stored for this bank / user.
    * 429 — a scrape is already running.
    * 500 — credential lookup failed.
    """
    user_id = _parse_user_id(x_user_id)
    _validate_credentials_exist(user_id, bank)

    if _SCRAPE_SEMAPHORE.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A sync is already in progress. Please wait and retry.",
        )

    job_id = str(uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "user_id": str(user_id),
        "bank": bank,
    }

    asyncio.create_task(_background_sync_accounts_task(job_id, user_id, bank))
    asyncio.create_task(_keepalive_while_running(job_id))

    return SyncJobStartResponse(job_id=job_id, status="pending")


@router.post(
    "/accounts/sync/{bank}/credit-cards",
    response_model=SyncJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a credit-card-only sync job",
)
async def start_sync_cc_job(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> SyncJobStartResponse:
    """Start a background sync that scrapes credit card accounts and statement transactions only.

    For NBE this calls ``scraper.scrape_credit_cards()`` instead of the full
    ``scraper.scrape()``.  For all other banks the full ``scrape()`` is used.

    HTTP response
    -------------
    * 202 — job started. Poll /accounts/sync/status/{job_id} for results.
    * 404 — no credentials stored for this bank / user.
    * 429 — a scrape is already running.
    * 500 — credential lookup failed.
    """
    user_id = _parse_user_id(x_user_id)
    _validate_credentials_exist(user_id, bank)

    if _SCRAPE_SEMAPHORE.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A sync is already in progress. Please wait and retry.",
        )

    job_id = str(uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "user_id": str(user_id),
        "bank": bank,
    }

    asyncio.create_task(_background_sync_cc_task(job_id, user_id, bank))
    asyncio.create_task(_keepalive_while_running(job_id))

    return SyncJobStartResponse(job_id=job_id, status="pending")


@router.post(
    "/accounts/sync/{bank}/certificates",
    response_model=SyncJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a certificates-only sync job",
)
async def start_sync_certificates_job(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> SyncJobStartResponse:
    """Start a background sync that scrapes certificate/term-deposit accounts only.

    For NBE this calls ``scraper.scrape_certificates()`` instead of the full
    ``scraper.scrape()``.  For all other banks the full ``scrape()`` is used.

    HTTP response
    -------------
    * 202 — job started. Poll /accounts/sync/status/{job_id} for results.
    * 404 — no credentials stored for this bank / user.
    * 429 — a scrape is already running.
    * 500 — credential lookup failed.
    """
    user_id = _parse_user_id(x_user_id)
    _validate_credentials_exist(user_id, bank)

    if _SCRAPE_SEMAPHORE.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A sync is already in progress. Please wait and retry.",
        )

    job_id = str(uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "user_id": str(user_id),
        "bank": bank,
    }

    asyncio.create_task(_background_sync_certificates_task(job_id, user_id, bank))
    asyncio.create_task(_keepalive_while_running(job_id))

    return SyncJobStartResponse(job_id=job_id, status="pending")
