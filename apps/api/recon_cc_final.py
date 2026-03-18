"""Final CC recon: select March 2026, click Submit, capture statement transactions."""
from __future__ import annotations
import asyncio, sys, argparse, json
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

        # Intercept ALL API calls containing credit card data
        api_calls = []
        async def on_response(resp):
            url = resp.url
            if any(k in url for k in ['credit', 'card', 'statement', 'transaction', 'billing', 'digx']):
                try:
                    body = await resp.text()
                    api_calls.append({'url': url, 'status': resp.status, 'body': body[:2000]})
                except Exception:
                    api_calls.append({'url': url, 'status': resp.status, 'body': ''})
        page.on("response", on_response)

        # Login
        print("[cc-final] Logging in...")
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

        # Navigate to card statement via CCA → hover → menu → Card Statement
        await page.click("li.CCA a", timeout=10_000)
        await asyncio.sleep(5)
        cc_row = page.locator("li.flip-account-list__items").first
        await cc_row.hover()
        await asyncio.sleep(2)
        await page.locator("a.menu-icon").first.click()
        await asyncio.sleep(2)
        await page.click("span:has-text('Card Statement')", timeout=5_000)
        await asyncio.sleep(8)
        print(f"[cc-final] On statement page. URL: {page.url}")

        # Wait for year/month selectors
        await page.wait_for_selector("#selectYear", timeout=10_000)

        # Select year 2026 using Oracle JET select
        print("[cc-final] Selecting year 2026...")
        # Oracle JET select: click the choice display, then click the option
        await page.click("#oj-select-choice-selectYear")
        await asyncio.sleep(1)
        # Click 2026 option
        year_option = page.locator("#oj-listbox-results-selectYear li").filter(has_text="2026").first
        await year_option.click()
        await asyncio.sleep(1)

        print("[cc-final] Selecting month March...")
        await page.click("#oj-select-choice-selectMonth")
        await asyncio.sleep(1)
        # Click March
        month_option = page.locator("#oj-listbox-results-selectMonth li").filter(has_text="Mar").first
        await month_option.click()
        await asyncio.sleep(1)

        print("[cc-final] Clicking Submit...")
        await page.click("button:has-text('Submit')")
        await asyncio.sleep(10)

        await page.screenshot(path=str(_OUT / "cc_final_result.png"), full_page=False)
        cc_html = await page.content()
        (_OUT / "cc_final_result.html").write_text(cc_html, encoding="utf-8")
        print(f"[cc-final] Saved cc_final_result.html ({len(cc_html):,} bytes)")

        page_text = await page.inner_text("body")
        (_OUT / "cc_final_text.txt").write_text(page_text, encoding="utf-8")
        print(f"[cc-final] Page text:\n{page_text[:1500]}")

        # Check for table data
        td_ids = await page.evaluate("() => Array.from(document.querySelectorAll('td[id]')).map(el => el.id).slice(0,20)")
        print(f"[cc-final] td[id] samples: {td_ids}")

        oj_tables = await page.evaluate("() => Array.from(document.querySelectorAll('oj-table')).map(el => ({id:el.id, text:el.innerText.trim().substring(0,100)}))")
        print(f"[cc-final] oj-table elements: {oj_tables}")

        # Save all API calls
        (_OUT / "cc_final_api_calls.txt").write_text(
            "\n\n".join(f"[{c['status']}] {c['url']}\n{c['body']}" for c in api_calls),
            encoding="utf-8"
        )
        print(f"[cc-final] {len(api_calls)} API calls captured → cc_final_api_calls.txt")
        for c in api_calls:
            print(f"  {c['status']} {c['url'][:100]}")

        print(f"\n[cc-final] Done. Files in: {_OUT}")
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
