"""Local BDC Retail scraper runner.

Run this from your Egyptian machine (Render is geo-blocked by BDC).
It scrapes BDC Retail and upserts results directly into Supabase.

Usage:
    cd apps/api
    uv run python run_bdc_local.py <username> <password> <user_id>

    # Or with encrypted credentials from the DB:
    uv run python run_bdc_local.py --encrypted <enc_user> <enc_pass> <user_id>

Example:
    uv run python run_bdc_local.py 9004343 FADYhabi22 cbb920f1-d489-4c55-86da-7a453b58658c
"""

from __future__ import annotations

import asyncio
import logging
import sys
from uuid import UUID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bdc_local")


async def main() -> None:
    args = sys.argv[1:]

    encrypted = False
    if args and args[0] == "--encrypted":
        encrypted = True
        args = args[1:]

    if len(args) != 3:
        print(__doc__)
        sys.exit(1)

    raw_user, raw_pass, user_id_str = args
    user_id = UUID(user_id_str)

    # Resolve credentials
    if encrypted:
        from app.config import settings
        from app.crypto import decrypt

        username = decrypt(raw_user, settings.encryption_key)
        password = decrypt(raw_pass, settings.encryption_key)
        logger.info("Decrypted credentials for user %s", user_id)
    else:
        username, password = raw_user, raw_pass

    # Build Supabase async client
    from supabase import create_async_client

    from app.config import settings

    supabase = await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )

    # Scrape
    from app.scrapers.bdc_retail import BDCRetailScraper

    logger.info("Starting BDC Retail scrape for user %s", user_id)
    scraper = BDCRetailScraper(username=username, password=password)
    result = await scraper.scrape()

    logger.info(
        "Scrape complete — %d account(s), %d transaction(s)",
        len(result.accounts),
        len(result.transactions),
    )
    for a in result.accounts:
        logger.info(
            "  Account: %s %s %s balance=%s",
            a.bank_name,
            a.account_type,
            a.account_number_masked,
            a.balance,
        )

    # Run pipeline
    from app.pipeline.runner import run_pipeline

    pipeline_result = await run_pipeline(
        result=result,
        user_id=user_id,
        supabase_client=supabase,
    )

    logger.info(
        "Pipeline complete — account_id=%s new_txns=%d skipped=%d",
        pipeline_result.account_id,
        pipeline_result.transactions_new,
        pipeline_result.transactions_skipped,
    )
    print("\nDone! Check your FinPilot dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
