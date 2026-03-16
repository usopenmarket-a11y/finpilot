"""Sync router — trigger a bank sync using stored credentials.

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

import logging
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
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


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class SyncResponse(BaseModel):
    """Result of a sync triggered from stored credentials."""

    bank: str
    account_number_masked: str
    transactions_scraped: int
    transactions_saved: int
    synced_at: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_user_id(raw: Optional[str]) -> UUID:
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


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    "/accounts/sync/{bank}",
    response_model=SyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync a bank account using stored credentials",
)
async def sync_bank(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
) -> SyncResponse:
    """Read stored encrypted credentials, run the scraper and ETL pipeline.

    HTTP error mapping
    ------------------
    * 404 — no credentials stored for this bank / user combination.
    * 422 — stored credential token is malformed (corrupt DB value).
    * 401 — GCM tag mismatch or bank rejected credentials.
    * 504 — bank portal timed out.
    * 502 — could not parse bank portal response.
    * 503 — bank portal unreachable.
    * 500 — unexpected error.
    """
    user_id = _parse_user_id(x_user_id)

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve stored credentials",
        ) from exc

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active credentials found for bank {bank}",
        )

    row = response.data
    enc_username: str = row["encrypted_username"]
    enc_password: str = row["encrypted_password"]

    # ------------------------------------------------------------------
    # Step 2 — decrypt credentials.
    # These variables must never appear in any log call.
    # ------------------------------------------------------------------
    try:
        username = decrypt(enc_username, settings.encryption_key)
        password = decrypt(enc_password, settings.encryption_key)
    except CryptoError as exc:
        logger.warning("Stored credential token is malformed for bank=%s", bank)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stored credential token is malformed",
        ) from exc
    except ValueError as exc:
        logger.warning("Stored credential token authentication failed for bank=%s", bank)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Stored credential token could not be authenticated",
        ) from exc

    # ------------------------------------------------------------------
    # Step 3 — run the scraper.
    # ------------------------------------------------------------------
    scraper_class = _SCRAPER_MAP[bank]
    scraper = scraper_class(username=username, password=password)

    logger.info("Sync initiated via stored credentials", extra={"bank": bank})
    try:
        result = await scraper.scrape()
    except ScraperLoginError:
        logger.warning("Sync failed: bank rejected credentials", extra={"bank": bank})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bank credentials",
        )
    except ScraperTimeoutError:
        logger.warning("Sync failed: portal timed out", extra={"bank": bank})
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Bank portal timed out",
        )
    except ScraperParseError:
        logger.warning("Sync failed: could not parse portal response", extra={"bank": bank})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to parse bank portal response",
        )
    except BankPortalUnreachableError:
        logger.warning("Sync failed: portal unreachable", extra={"bank": bank})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bank portal unreachable",
        )
    except Exception as exc:
        logger.error("Sync failed: unexpected error", extra={"bank": bank}, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scraper error",
        ) from exc
    finally:
        del username, password

    # ------------------------------------------------------------------
    # Step 4 — run the ETL pipeline.
    # ------------------------------------------------------------------
    transactions_saved = 0
    try:
        from supabase import create_client as _mk  # local import to keep top-of-file clean

        pipeline_client = _mk(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        pipeline_result = await run_pipeline(result, user_id=user_id, supabase_client=pipeline_client)
        transactions_saved = pipeline_result.transactions_new
    except Exception as exc:
        logger.warning("Pipeline failed during sync (scrape succeeded): %s", exc, extra={"bank": bank})

    # ------------------------------------------------------------------
    # Step 5 — update last_synced_at (non-fatal).
    # ------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        update_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        update_client.table("bank_credentials").update(
            {"last_synced_at": now_iso}
        ).eq("user_id", str(user_id)).eq("bank", bank).execute()
    except Exception:
        pass  # non-fatal

    transactions_scraped = len(result.transactions)
    logger.info(
        "Sync completed",
        extra={
            "bank": bank,
            "account_number_masked": result.account.account_number_masked,
            "transactions_scraped": transactions_scraped,
            "transactions_saved": transactions_saved,
        },
    )

    return SyncResponse(
        bank=result.account.bank_name,
        account_number_masked=result.account.account_number_masked,
        transactions_scraped=transactions_scraped,
        transactions_saved=transactions_saved,
        synced_at=now_iso,
    )
