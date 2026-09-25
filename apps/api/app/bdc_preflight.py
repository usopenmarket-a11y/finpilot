"""Check hosted BDC connectivity without bank credentials or database writes.

Run from apps/api: python -m app.bdc_preflight
Uses the same Patchright browser/proxy configuration as webapp syncs.
"""

from __future__ import annotations

import asyncio
import ipaddress
from uuid import uuid4

from app.scrapers.base import ScraperUnavailableError
from app.scrapers.bdc_kony import (
    _APP_URL,
    _LOGIN_IFRAME_MARKER,
    _NAV_TIMEOUT_MS,
    _SEL_PASSWORD,
    BDCKonyScraper,
)
from app.scrapers.bdc_proxy import get_bdc_proxy


class PreflightError(Exception):
    """An actionable diagnostic that never includes credentials or raw responses."""


async def _check_egress(page) -> str:
    # A fresh URL prevents a browser cache hit from masking IP rotation.
    response = await page.goto(
        f"https://www.cloudflare.com/cdn-cgi/trace?bdc_check={uuid4().hex}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    if response is None or response.status != 200:
        raise PreflightError("Proxy location check failed; no bank login was attempted.")
    fields = dict(
        line.split("=", 1) for line in (await response.text()).splitlines() if "=" in line
    )
    if fields.get("loc") != "EG":
        raise PreflightError("Proxy exit is not confirmed in Egypt. Select country Egypt first.")
    try:
        return str(ipaddress.ip_address(fields.get("ip", "")))
    except ValueError:
        raise PreflightError("Proxy location check returned no valid exit IP.") from None


async def check_connectivity() -> None:
    get_bdc_proxy(required=True)
    scraper = BDCKonyScraper(username="", password="")
    browser, context, page = await scraper._launch_browser()
    try:
        first_ip = await _check_egress(page)
        response = await page.goto(_APP_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        if response is None or response.status >= 400:
            raise PreflightError(
                "BDC portal rejected the connection. Check provider target access."
            )
        # Check the actual login form, rather than treating a 200 block page as success.
        for _ in range(30):
            ready = False
            for frame in page.frames:
                if _LOGIN_IFRAME_MARKER in (frame.url or ""):
                    ready = await frame.locator(_SEL_PASSWORD).is_visible()
                    if ready:
                        break
            if ready:
                break
            await page.wait_for_timeout(2_000)
        else:
            raise PreflightError("BDC login form did not load through the proxy.")
        second_page = await context.new_page()
        if await _check_egress(second_page) != first_ip:
            raise PreflightError("Proxy IP changed during the check. Configure a sticky session.")
        print("PASS: Egyptian exit, BDC login form loaded, exit IP unchanged across checks.")
        print("No bank login or database writes performed. Authenticated sync remains unverified.")
    finally:
        await scraper._close_browser(browser)


def main() -> int:
    try:
        asyncio.run(check_connectivity())
    except (PreflightError, ScraperUnavailableError) as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception:
        # Browser errors can contain proxy credentials. Never print their text
        # or traceback, nor save screenshots/network traces of the login form.
        print("FAIL: Browser/network check failed. Check proxy authentication, access and timeout.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
