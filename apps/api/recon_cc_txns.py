"""Recon: get CC statement transactions by selecting year/month and clicking Submit."""
from __future__ import annotations
import asyncio, sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app.config import settings
from app.crypto import decrypt

_OUT = Path("/tmp/finpilot_debug/nbe_recon")
_LOGIN_URL = "https://www.alahlynet.com.eg/?page=home"

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

        # Track API calls
        api_calls = []
        async def on_response(resp):
            url = resp.url
            if any(k in url for k in ['credit', 'card', 'statement', 'transaction']):
                try:
                    body = await resp.text()
                    api_calls.append({'url': url, 'status': resp.status, 'body': body[:500]})
                except Exception:
                    api_calls.append({'url': url, 'status': resp.status, 'body': ''})
        page.on("response", on_response)

        # Login
        print("[cc-txns] Logging in...")
        await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
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
                    await el.click()
                    break
            except Exception:
                continue
        await asyncio.sleep(8)
        print(f"[cc-txns] Logged in. URL: {page.url}")

        # Navigate to CCA widget + hover + menu + Card Statement
        await page.click("li.CCA a", timeout=10_000)
        await asyncio.sleep(5)
        cc_row = page.locator("div.flip-account.CCA li.flip-account-list__items").first
        if not await cc_row.count():
            cc_row = page.locator("li.flip-account-list__items").first
        await cc_row.hover()
        await asyncio.sleep(2)
        menu_icon = page.locator("a.menu-icon").first
        await menu_icon.click()
        await asyncio.sleep(2)
        await page.click("span:has-text('Card Statement')", timeout=5_000)
        await asyncio.sleep(8)
        print(f"[cc-txns] On CC statement page. URL: {page.url}")

        # Wait for year/month selectors to render
        await page.wait_for_selector("#selectYear", timeout=10_000)
        print("[cc-txns] Year/month selectors found")

        # Get available years
        years = await page.evaluate("""() => {
            const ul = document.querySelector('#oj-listbox-results-selectYear');
            if (ul) {
                return Array.from(ul.querySelectorAll('li')).map(li => ({
                    id: li.id, text: li.innerText.trim(), class: li.className
                }));
            }
            // Try to open the select to get options
            const sel = document.querySelector('#selectYear');
            if (sel) {
                return sel.innerText.trim();
            }
            return null;
        }""")
        print(f"[cc-txns] Years (before open): {years}")

        # Click the year select to open dropdown
        year_sel = await page.query_selector("#oj-select-choice-selectYear")
        if year_sel:
            await year_sel.click()
            await asyncio.sleep(2)
            await page.screenshot(path=str(_OUT / "cc_year_dropdown.png"), full_page=False)

            # Get options now that dropdown is open
            year_options = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('#oj-listbox-results-selectYear li'))
                    .map(li => ({id: li.id, text: li.innerText.trim(), value: li.getAttribute('data-oj-item-value')}));
            }""")
            print(f"[cc-txns] Year options: {year_options}")
            (_OUT / "cc_year_options.txt").write_text(
                "\n".join(f"{o}" for o in year_options), encoding="utf-8"
            )

            # Select current year (2026)
            current_year = "2026"
            year_li = await page.query_selector(f"#oj-listbox-results-selectYear li:has-text('{current_year}')")
            if year_li:
                await year_li.click()
                print(f"[cc-txns] Selected year: {current_year}")
                await asyncio.sleep(2)
            else:
                # Select first available year
                first_year = await page.query_selector("#oj-listbox-results-selectYear li")
                if first_year:
                    year_text = await first_year.inner_text()
                    await first_year.click()
                    print(f"[cc-txns] Selected first year: {year_text}")
                    await asyncio.sleep(2)

        # Click month select
        month_sel = await page.query_selector("#oj-select-choice-selectMonth")
        if month_sel:
            await month_sel.click()
            await asyncio.sleep(2)
            month_options = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('#oj-listbox-results-selectMonth li'))
                    .map(li => ({id: li.id, text: li.innerText.trim()}));
            }""")
            print(f"[cc-txns] Month options: {month_options}")
            (_OUT / "cc_month_options.txt").write_text(
                "\n".join(f"{o}" for o in month_options), encoding="utf-8"
            )

            # Select first/current month
            first_month = await page.query_selector("#oj-listbox-results-selectMonth li")
            if first_month:
                month_text = await first_month.inner_text()
                await first_month.click()
                print(f"[cc-txns] Selected month: {month_text}")
                await asyncio.sleep(2)

        # Click Submit
        print("[cc-txns] Clicking Submit...")
        submit_btn = await page.query_selector("button:has-text('Submit'), button:has-text('SUBMIT')")
        if submit_btn:
            await submit_btn.click()
            print("[cc-txns] Submit clicked")
        else:
            # Try the OK button
            ok_btn = await page.query_selector("button:has-text('OK')")
            if ok_btn:
                await ok_btn.click()
                print("[cc-txns] OK clicked")

        # Wait for results
        await asyncio.sleep(10)
        await page.screenshot(path=str(_OUT / "cc_txns_result.png"), full_page=False)
        cc_result_html = await page.content()
        (_OUT / "cc_txns_result.html").write_text(cc_result_html, encoding="utf-8")
        print(f"[cc-txns] Saved cc_txns_result.html ({len(cc_result_html):,} bytes)")

        # Get page text
        page_text = await page.inner_text("body")
        (_OUT / "cc_txns_text.txt").write_text(page_text, encoding="utf-8")
        print(f"[cc-txns] Page text ({len(page_text)} chars) → cc_txns_text.txt")

        # Look for tables / lists / transaction rows
        elements = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('oj-table,table,tr,li[class*="txn"],li[class*="transaction"],div[class*="transaction"]')).map(el => ({
                tag: el.tagName, id: el.id||'',
                className: el.className.substring(0,80),
                text: el.innerText.trim().substring(0,150),
                visible: el.offsetParent !== null,
            })).filter(e => e.text.length > 5).slice(0, 30);
        }""")
        (_OUT / "cc_txns_elements.txt").write_text(
            "\n\n".join(f"[{i}] {e}" for i, e in enumerate(elements)),
            encoding="utf-8"
        )
        print(f"[cc-txns] {len(elements)} elements → cc_txns_elements.txt")

        # Log API calls
        if api_calls:
            (_OUT / "cc_api_calls.txt").write_text(
                "\n\n".join(f"[{c['status']}] {c['url']}\n{c['body']}" for c in api_calls),
                encoding="utf-8"
            )
            print(f"[cc-txns] {len(api_calls)} API calls → cc_api_calls.txt")
            for c in api_calls:
                print(f"  {c['status']} {c['url'][:100]}")

        print(f"\n[cc-txns] Done. Files in: {_OUT}")
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
