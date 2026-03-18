"""Recon: navigate to CC statement via hover → menu-icon → Account Activity."""
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

        # Login
        print("[cc-stmt] Logging in...")
        await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)
        await page.fill("#login_username", username)
        await asyncio.sleep(1)
        await page.click("#username-button")
        await page.wait_for_selector("#login_password", timeout=15_000)
        await page.fill("#login_password", password)
        await asyncio.sleep(1)
        # Find password submit button
        for sel in ["button.btn-login-2", "#password-button"]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    break
            except Exception:
                continue
        await asyncio.sleep(8)
        print(f"[cc-stmt] Logged in. URL: {page.url}")

        # Click CCA widget
        print("[cc-stmt] Clicking CCA widget...")
        await page.click("li.CCA a", timeout=10_000)
        await asyncio.sleep(5)
        await page.screenshot(path=str(_OUT / "cc_stmt_step1.png"), full_page=False)
        print(f"[cc-stmt] After CCA click. URL: {page.url}")

        # Hover over the CC account row to reveal menu-icon
        print("[cc-stmt] Hovering over CC account row...")
        cc_row = page.locator("div.flip-account.CCA li.flip-account-list__items").first
        if not await cc_row.count():
            cc_row = page.locator("li.flip-account-list__items").first
        await cc_row.hover()
        await asyncio.sleep(2)
        await page.screenshot(path=str(_OUT / "cc_stmt_step2_hover.png"), full_page=False)

        # Look for and click menu-icon
        menu_icon = page.locator("a.menu-icon").first
        if await menu_icon.count():
            print("[cc-stmt] Clicking menu-icon...")
            await menu_icon.click()
            await asyncio.sleep(2)
            await page.screenshot(path=str(_OUT / "cc_stmt_step3_menu.png"), full_page=False)

            # Dump all visible elements after menu open
            menu_elements = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a,li,span,button')).filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && el.innerText.trim().length > 0;
                }).map(el => ({
                    tag: el.tagName,
                    className: el.className.substring(0,80),
                    text: el.innerText.trim().substring(0,60),
                }));
            }""")
            (_OUT / "cc_stmt_menu_elements.txt").write_text(
                "\n".join(f"[{i}] {e['tag']} class={e['className']!r} text={e['text']!r}"
                          for i, e in enumerate(menu_elements)),
                encoding="utf-8"
            )
            print(f"[cc-stmt] {len(menu_elements)} elements after menu open → cc_stmt_menu_elements.txt")

            # Try clicking various statement/activity options
            stmt_options = [
                "span:has-text('Card Statement')",
                "a:has-text('Card Statement')",
                "span:has-text('Account Activity')",
                "a:has-text('Account Activity')",
                "span:has-text('Statement')",
                "li:has-text('Card Statement')",
            ]
            clicked = False
            for sel in stmt_options:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        print(f"[cc-stmt] Clicking: {sel}")
                        await el.click()
                        await asyncio.sleep(8)
                        clicked = True
                        break
                except Exception:
                    continue

            if clicked:
                await page.screenshot(path=str(_OUT / "cc_stmt_step4_page.png"), full_page=False)
                cc_html = await page.content()
                (_OUT / "cc_stmt_page.html").write_text(cc_html, encoding="utf-8")
                print(f"[cc-stmt] Saved cc_stmt_page.html. URL: {page.url}")

                # Wait for AJAX
                print("[cc-stmt] Waiting for transaction data to load...")
                # Try clicking Apply
                for sel in ["button:has-text('Apply')", "button:has-text('Search')"]:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            await el.click()
                            print(f"[cc-stmt] Clicked Apply/Search")
                            await asyncio.sleep(8)
                            break
                    except Exception:
                        continue

                await page.screenshot(path=str(_OUT / "cc_stmt_loaded.png"), full_page=False)
                cc_loaded_html = await page.content()
                (_OUT / "cc_stmt_loaded.html").write_text(cc_loaded_html, encoding="utf-8")

                # Get page text
                page_text = await page.inner_text("body")
                (_OUT / "cc_stmt_text.txt").write_text(page_text, encoding="utf-8")
                print(f"[cc-stmt] Page text ({len(page_text)} chars) → cc_stmt_text.txt")

                # Find all tables
                tables = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('oj-table,table,[id*="Statement"],[id*="statement"]')).map(el => ({
                        tag: el.tagName, id: el.id||'',
                        className: el.className.substring(0,80),
                        cells: document.querySelectorAll('[id^="' + (el.id||'X') + ':"]').length,
                        text: el.innerText.trim().substring(0,200),
                    }));
                }""")
                (_OUT / "cc_stmt_tables.txt").write_text(
                    "\n\n".join(f"[{i}] tag={e['tag']} id={e['id']!r} cells={e['cells']}\n  text={e['text']!r}"
                                for i, e in enumerate(tables)),
                    encoding="utf-8"
                )
                print(f"[cc-stmt] {len(tables)} table elements → cc_stmt_tables.txt")

                # Look for any oj-table IDs
                oj_ids = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('oj-table')).map(el => el.id);
                }""")
                print(f"[cc-stmt] oj-table IDs: {oj_ids}")

                # Look for td cells with IDs that contain the table pattern
                cell_ids = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('td[id]')).map(el => el.id).slice(0,20);
                }""")
                print(f"[cc-stmt] td IDs sample: {cell_ids}")
            else:
                print("[cc-stmt] No statement option found in menu")
        else:
            print("[cc-stmt] menu-icon not found after hover")
            # Try direct JS click on menu icon
            await page.evaluate("""() => {
                const icon = document.querySelector('a.menu-icon');
                if (icon) icon.click();
            }""")
            await asyncio.sleep(2)
            await page.screenshot(path=str(_OUT / "cc_stmt_js_menu.png"), full_page=False)

        print(f"\n[cc-stmt] Done. Files in: {_OUT}")
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
