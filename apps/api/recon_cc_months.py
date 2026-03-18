"""Try all months to find CC statement data."""
from __future__ import annotations
import asyncio, sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app.config import settings
from app.crypto import decrypt

_OUT = Path("/tmp/finpilot_debug/nbe_recon")

async def run(username: str, password: str) -> None:
    from playwright.async_api import async_playwright
    _OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US", timezone_id="Africa/Cairo",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = await context.new_page()

        api_calls = []
        async def on_response(resp):
            url = resp.url
            if 'listStatements' in url or 'listUnbilled' in url or 'unbilled' in url.lower():
                try:
                    body = await resp.text()
                    api_calls.append({'url': url, 'status': resp.status, 'body': body[:3000]})
                    print(f"  [api] {resp.status} {url}")
                    print(f"  {body[:200]}")
                except Exception as e:
                    print(f"  [api err] {e}")
        page.on("response", on_response)

        # Login
        print("[cc-months] Logging in...")
        await page.goto("https://www.alahlynet.com.eg/?page=home", wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)
        await page.fill("#login_username", username)
        await asyncio.sleep(1)
        await page.click("#username-button")
        await page.wait_for_selector("#login_password", timeout=15_000)
        await page.fill("#login_password", password)
        await asyncio.sleep(1)
        for sel in ["button.btn-login-2", "#password-button"]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click(); break
            except Exception: continue
        await asyncio.sleep(8)

        # Navigate to CC statement page
        await page.wait_for_selector("li.CCA a", timeout=15_000)
        await page.click("li.CCA a", timeout=10_000)
        await asyncio.sleep(6)
        # Wait for CC account rows to appear in the CCA flip-card
        try:
            await page.wait_for_selector("div.flip-account.CCA li.flip-account-list__items", timeout=10_000)
            await page.locator("div.flip-account.CCA li.flip-account-list__items").first.hover()
        except Exception:
            # Fallback: use any flip-account-list__items
            await page.locator("li.flip-account-list__items").first.hover()
        await asyncio.sleep(2)
        await page.locator("a.menu-icon").first.click()
        await asyncio.sleep(2)
        await page.click("span:has-text('Card Statement')", timeout=5_000)
        await asyncio.sleep(8)
        await page.wait_for_selector("#selectYear", timeout=10_000)
        print(f"[cc-months] On statement page")

        # Try all months for 2025 and 2026 to find data
        months = [('Jan',1), ('Feb',2), ('Mar',3), ('Apr',4), ('May',5), ('Jun',6),
                  ('Jul',7), ('Aug',8), ('Sep',9), ('Oct',10), ('Nov',11), ('Dec',12)]

        for year in ['2025', '2026']:
            print(f"\n[cc-months] Trying year {year}...")
            # Select year
            await page.click("#oj-select-choice-selectYear")
            await asyncio.sleep(1)
            year_opt = page.locator("#oj-listbox-results-selectYear li").filter(has_text=year).first
            if await year_opt.count():
                await year_opt.click()
                await asyncio.sleep(1)
            else:
                print(f"  Year {year} not available, skipping")
                # Close dropdown
                await page.keyboard.press("Escape")
                continue

            for month_name, month_num in months:
                await page.click("#oj-select-choice-selectMonth")
                await asyncio.sleep(1)
                month_opt = page.locator("#oj-listbox-results-selectMonth li").filter(has_text=month_name).first
                if await month_opt.count():
                    await month_opt.click()
                    await asyncio.sleep(1)
                else:
                    await page.keyboard.press("Escape")
                    continue

                await page.click("button:has-text('Submit')")
                await asyncio.sleep(5)

                # Check if we got data
                page_text = await page.inner_text("body")
                if "No details found" in page_text or "no details" in page_text.lower():
                    print(f"  {year}/{month_num}: No data")
                elif "Error" in page_text and "Please Select" in page_text:
                    print(f"  {year}/{month_num}: Selection error")
                else:
                    print(f"  {year}/{month_num}: GOT DATA!")
                    # Save this
                    html = await page.content()
                    (_OUT / f"cc_stmt_{year}_{month_num:02d}.html").write_text(html, encoding="utf-8")
                    txt = await page.inner_text("body")
                    (_OUT / f"cc_stmt_{year}_{month_num:02d}_text.txt").write_text(txt, encoding="utf-8")
                    print(f"  Saved cc_stmt_{year}_{month_num:02d}.html")
                    print(f"  Page text preview:\n{txt[:500]}")

        if api_calls:
            (_OUT / "cc_months_api.txt").write_text(
                "\n\n".join(f"[{c['status']}] {c['url']}\n{c['body']}" for c in api_calls),
                encoding="utf-8"
            )
            print(f"\n[cc-months] {len(api_calls)} API calls → cc_months_api.txt")

        print(f"\n[cc-months] Done.")
        await asyncio.sleep(3)
        await browser.close()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enc-user"); parser.add_argument("--enc-pass")
    args = parser.parse_args()
    username = decrypt(args.enc_user, settings.encryption_key)
    password = decrypt(args.enc_pass, settings.encryption_key)
    asyncio.run(run(username, password))

if __name__ == "__main__":
    main()
