"""Scrape router — triggers a bank scrape for the authenticated user.

Security contract
-----------------
* Decrypted credential strings are local variables that exist only for the
  duration of the handler call.  They are never assigned to attributes,
  module-level names, or any structure that outlives the stack frame.
* ``encrypted_username``, ``encrypted_password``, and the decrypted
  plaintext values MUST NOT appear in any log call.  Log only the bank name,
  masked account number, and transaction count.
* The scraper receives the credentials directly; once ``await scraper.scrape()``
  returns (or raises), the local variable references are the only holders and
  Python's reference-counting GC will collect them promptly when the frame exits.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.crypto import CryptoError, decrypt
from app.scrapers import (
    BankPortalUnreachableError,
    CIBScraper,
    NBEScraper,
    ScraperLoginError,
    ScraperParseError,
    ScraperTimeoutError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scrape"])

# ---------------------------------------------------------------------------
# Static scraper dispatch table — avoids any dynamic class lookup on
# user-supplied input.
# ---------------------------------------------------------------------------
_SCRAPER_MAP = {
    "NBE": NBEScraper,
    "CIB": CIBScraper,
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScrapeRequest(BaseModel):
    """POST /api/v1/scrape — trigger a bank account scrape.

    ``encrypted_username`` and ``encrypted_password`` are AES-256-GCM tokens
    produced by ``crypto.encrypt()``.  The server decrypts them using the
    ``settings.encryption_key`` — the client must have encrypted them with
    the same key.

    Extra fields are rejected to prevent parameter-pollution attacks.
    """

    model_config = ConfigDict(extra="forbid")

    bank: Literal["NBE", "CIB"] = Field(
        description="Target bank — must be one of the supported scrapers"
    )
    encrypted_username: str = Field(
        description="AES-256-GCM token of the bank portal username"
    )
    encrypted_password: str = Field(
        description="AES-256-GCM token of the bank portal password"
    )


class ScrapeResponse(BaseModel):
    """Successful scrape result.

    Raw transaction records are intentionally excluded — the pipeline layer
    handles persistence.  Only the aggregate summary is returned to the caller.
    """

    bank: str = Field(description="Bank code that was scraped")
    account_number_masked: str = Field(
        description="Last 4 digits of the account number, prefixed with ****"
    )
    balance: Decimal = Field(description="Current account balance reported by the bank portal")
    currency: str = Field(description="ISO 4217 currency code")
    transactions_scraped: int = Field(
        description="Number of transactions returned by the scraper"
    )


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    "/scrape",
    response_model=ScrapeResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger a bank account scrape",
)
async def trigger_scrape(body: ScrapeRequest) -> ScrapeResponse:
    """Decrypt credentials, run the bank scraper, and return a summary.

    HTTP error mapping
    ------------------
    * 422 — ``CryptoError``: token is malformed or base64-invalid.
    * 401 — ``ValueError`` from decrypt: GCM tag mismatch (wrong key or
      tampered ciphertext), or bank portal rejected the credentials.
    * 504 — ``ScraperTimeoutError``: bank portal did not respond in time.
    * 502 — ``ScraperParseError``: scraped HTML did not match expected layout.
    * 503 — ``BankPortalUnreachableError``: portal returned a network/5xx error.
    * 500 — any other unexpected exception from the scraper layer.
    """
    # ------------------------------------------------------------------
    # Step 1 — decrypt credentials.
    # These two local variables must never be passed to logger.* calls.
    # ------------------------------------------------------------------
    try:
        username = decrypt(body.encrypted_username, settings.encryption_key)
        password = decrypt(body.encrypted_password, settings.encryption_key)
    except CryptoError as exc:
        logger.warning("Credential token decryption failed (malformed token): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Credential token is malformed or invalid",
        ) from exc
    except ValueError as exc:
        # GCM authentication tag verification failed — wrong key or tampering.
        logger.warning("Credential token authentication failed (bad key or tampered token)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential token could not be authenticated",
        ) from exc

    # ------------------------------------------------------------------
    # Step 2 — instantiate the correct scraper from the static dispatch table.
    # ------------------------------------------------------------------
    scraper_class = _SCRAPER_MAP[body.bank]  # KeyError impossible: Literal enforces membership
    scraper = scraper_class(username=username, password=password)

    # ------------------------------------------------------------------
    # Step 3 — run the scrape.  All exception types have explicit HTTP mappings.
    # ------------------------------------------------------------------
    logger.info("Scrape initiated", extra={"bank": body.bank})
    try:
        result = await scraper.scrape()
    except ScraperLoginError:
        logger.warning("Scrape failed: bank rejected credentials", extra={"bank": body.bank})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bank credentials",
        )
    except ScraperTimeoutError:
        logger.warning("Scrape failed: portal timed out", extra={"bank": body.bank})
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Bank portal timed out",
        )
    except ScraperParseError:
        logger.warning("Scrape failed: could not parse portal response", extra={"bank": body.bank})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to parse bank portal response",
        )
    except BankPortalUnreachableError:
        logger.warning("Scrape failed: portal unreachable", extra={"bank": body.bank})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bank portal unreachable",
        )
    except Exception as exc:
        logger.error(
            "Scrape failed: unexpected error",
            extra={"bank": body.bank},
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scraper error",
        ) from exc
    finally:
        # username and password go out of scope here.  Python's reference
        # counter will deallocate the str objects as soon as no other
        # references exist.  The scraper holds references via self._username /
        # self._password, but the scraper instance itself is also local and
        # will be collected when the frame exits.
        del username, password

    # ------------------------------------------------------------------
    # Step 4 — build a safe response from the scraper result.
    # Log only the masked account number and transaction count.
    # ------------------------------------------------------------------
    account = result.account
    transactions_scraped = len(result.transactions)

    logger.info(
        "Scrape completed",
        extra={
            "bank": body.bank,
            "account_number_masked": account.account_number_masked,
            "transactions_scraped": transactions_scraped,
        },
    )

    return ScrapeResponse(
        bank=account.bank_name,
        account_number_masked=account.account_number_masked,
        balance=account.balance,
        currency=account.currency,
        transactions_scraped=transactions_scraped,
    )
