"""
Local NBE scraper test — runs the scraper directly, no API, no Supabase.
Dumps CC statement item meta fields + all scraped data to stdout and /tmp/nbe_test_result.json.

Usage:
    cd apps/api
    uv run python test_nbe_local.py <username> <password>
    # or: python test_nbe_local.py <username> <password>
"""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path


def _serialise(obj: object) -> object:
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


async def main(username: str, password: str) -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    import app.scrapers.nbe as nbe_mod

    print("\n" + "=" * 60)
    print("NBE LOCAL SCRAPER TEST")
    print("=" * 60 + "\n")

    scraper = nbe_mod.NBEScraper()
    result = await scraper.scrape(username=username, password=password)

    print("\n" + "=" * 60)
    print("SCRAPE RESULT SUMMARY")
    print("=" * 60)
    print(f"Success:        {result.success}")
    print(f"Error:          {result.error_message}")
    print(f"Accounts:       {len(result.accounts)}")
    print(f"Transactions:   {len(result.transactions)}")

    print("\n--- ACCOUNTS ---")
    for acc in result.accounts:
        print(f"  {acc.account_type:15} {acc.account_number_masked}  {acc.currency} {acc.balance}")
        if acc.account_type == "credit_card":
            print(f"    credit_limit:    {acc.credit_limit}")
            print(f"    billed_amount:   {acc.billed_amount}")
            print(f"    unbilled_amount: {acc.unbilled_amount}")
        if acc.account_type in ("certificate", "deposit"):
            print(f"    interest_rate:   {acc.interest_rate}")
            print(f"    maturity_date:   {acc.maturity_date}")

    print("\n--- CC TRANSACTIONS (first 20) ---")
    cc_txns = [
        t
        for t in result.transactions
        if t.raw_data and "nbe_cc" in str(t.raw_data.get("source", ""))
    ]
    for tx in cc_txns[:20]:
        print(
            f"  {tx.transaction_date}  {tx.transaction_type:8}  {tx.currency} {tx.amount:>12}  {tx.description[:60]}"
        )

    print(f"\n  ... {len(cc_txns)} CC transactions total")

    # Save full result to JSON
    out = {
        "success": result.success,
        "error_message": result.error_message,
        "accounts": [{k: _serialise(v) for k, v in vars(acc).items()} for acc in result.accounts],
        "transactions": [
            {k: _serialise(v) for k, v in vars(tx).items()} for tx in result.transactions
        ],
    }
    out_path = Path("/tmp/nbe_test_result.json")
    out_path.write_text(json.dumps(out, indent=2, default=_serialise))
    print(f"\nFull result saved to: {out_path}")
    print("\nDone.\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <username> <password>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
