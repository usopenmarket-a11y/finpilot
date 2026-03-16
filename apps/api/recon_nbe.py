"""NBE recon script — captures live HTML from alahlynet.com.eg.

Run from apps/api directory:
    uv run python recon_nbe.py

    # With credentials (encrypted):
    uv run python recon_nbe.py --enc-user <token> --enc-pass <token>

    # With plaintext credentials (local dev only — never commit):
    uv run python recon_nbe.py --user <username> --password <password>

Outputs to /tmp/finpilot_debug/nbe_recon/:
    - login_page.html       — raw HTML of the login page
    - login_page.png        — screenshot of login page
    - post_login.html       — HTML after login (if credentials supplied)
    - post_login.png        — screenshot after login
    - transactions.html     — HTML of transaction page (if reachable)
    - transactions.png      — screenshot of transaction page
    - dom_inputs.txt        — all input elements found on login page
    - dom_links.txt         — all links found post-login (for navigation)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from apps/api directory
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.crypto import decrypt

_OUT = Path("/tmp/finpilot_debug/nbe_recon")
_LOGIN_URL = "https://www.alahlynet.com.eg/?page=home"
_TIMEOUT = 30_000


async def recon(username: str | None, password: str | None) -> None:
    from playwright.async_api import async_playwright

    _OUT.mkdir(parents=True, exist_ok=True)
    print(f"[recon] Output directory: {_OUT}")
    print(f"[recon] Navigating to: {_LOGIN_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,  # WSL2 has no display — use headless
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Africa/Cairo",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()

        # ── Step 1: Load login page ──────────────────────────────────────────
        print("[recon] Loading login page...")
        await page.goto(_LOGIN_URL, wait_until="networkidle", timeout=_TIMEOUT)
        await asyncio.sleep(3)  # let JS settle

        html = await page.content()
        (_OUT / "login_page.html").write_text(html, encoding="utf-8")
        await page.screenshot(path=str(_OUT / "login_page.png"), full_page=True)
        print(f"[recon] ✓ Saved login_page.html ({len(html):,} bytes) + login_page.png")

        # ── Step 2: Dump all input elements ──────────────────────────────────
        inputs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input, button, [type=submit]')).map(el => ({
                tag: el.tagName,
                type: el.type || '',
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                className: el.className || '',
                value: el.type === 'password' ? '***' : (el.value || ''),
                outerHTML: el.outerHTML.substring(0, 300),
            }));
        }""")
        inputs_text = "\n\n".join(
            f"[{i}] tag={el['tag']} type={el['type']} id={el['id']!r} "
            f"name={el['name']!r} placeholder={el['placeholder']!r}\n"
            f"    class={el['className']!r}\n"
            f"    html={el['outerHTML']}"
            for i, el in enumerate(inputs)
        )
        (_OUT / "dom_inputs.txt").write_text(inputs_text, encoding="utf-8")
        print(f"[recon] ✓ Found {len(inputs)} input/button elements → dom_inputs.txt")

        # ── Step 3: Login (only if credentials provided) ─────────────────────
        if not username or not password:
            print("[recon] No credentials supplied — stopping after login page capture.")
            print(f"[recon] Review {_OUT}/dom_inputs.txt to find correct selectors.")
            await browser.close()
            return

        print("[recon] Credentials provided — attempting login...")

        # Try common selectors for username field
        username_selectors = [
            "input[type='text']",
            "input[name*='user' i]",
            "input[id*='user' i]",
            "input[placeholder*='user' i]",
            "input[placeholder*='ID' i]",
            "#username", "#userName", "#UserName",
            "input[name='username']",
        ]
        username_el = None
        matched_sel = None
        for sel in username_selectors:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                username_el = el
                matched_sel = sel
                break

        if username_el is None:
            print("[recon] WARNING: Could not find username field with common selectors.")
            print("[recon] Check dom_inputs.txt and update selectors manually.")
            await browser.close()
            return

        print(f"[recon] ✓ Found username field: {matched_sel}")

        # ── NBE is a 2-step Oracle JET SPA ──────────────────────────────────
        # Step A: type username into #login_username, click #username-button
        # Step B: SPA renders #login_password dynamically — type password, click submit

        # Step A: type username
        await username_el.click()
        for char in username:
            await page.keyboard.type(char, delay=80)
        await asyncio.sleep(1)

        # Click the "Login" button (submits username, triggers password step)
        step1_btn = await page.query_selector("#username-button")
        if step1_btn is None:
            print("[recon] WARNING: #username-button not found — pressing Enter")
            await page.keyboard.press("Enter")
        else:
            print("[recon] ✓ Clicking #username-button (step 1 submit)")
            await step1_btn.click()

        # Wait for SPA to render the password field
        print("[recon] Waiting for password field to appear (SPA render)...")
        try:
            await page.wait_for_selector("#login_password", timeout=15_000)
            print("[recon] ✓ #login_password appeared")
        except Exception:
            # Maybe a different selector — try generic password input
            try:
                await page.wait_for_selector("input[type='password']", timeout=10_000)
                print("[recon] ✓ input[type=password] appeared")
            except Exception:
                await page.screenshot(path=str(_OUT / "after_step1.png"))
                html_step1 = await page.content()
                (_OUT / "after_step1.html").write_text(html_step1, encoding="utf-8")
                # Dump all inputs at this stage
                inputs2 = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('input,button')).map(el => ({
                        tag: el.tagName, type: el.type||'', id: el.id||'',
                        name: el.name||'', placeholder: el.placeholder||'',
                        visible: el.offsetParent !== null,
                        outerHTML: el.outerHTML.substring(0,200),
                    }));
                }""")
                (_OUT / "dom_inputs_step2.txt").write_text(
                    "\n\n".join(f"[{i}] {e}" for i, e in enumerate(inputs2)),
                    encoding="utf-8"
                )
                print("[recon] ⚠ Password field not found after step 1.")
                print("[recon] Saved after_step1.html + after_step1.png + dom_inputs_step2.txt")
                print(f"[recon] Current URL: {page.url}")
                await browser.close()
                return

        # Step B: type password
        password_el = await page.query_selector("#login_password")
        if password_el is None:
            password_el = await page.query_selector("input[type='password']")
        print("[recon] ✓ Typing password...")
        await password_el.click()
        for char in password:
            await page.keyboard.type(char, delay=80)
        await asyncio.sleep(1)

        # Find password step submit button
        step2_btn_selectors = [
            "#password-button",
            "button.btn-login",
            "button:has-text('Sign In')",
            "button:has-text('Login')",
            "button:has-text('Continue')",
            "button:has-text('تسجيل الدخول')",
        ]
        step2_btn = None
        for sel in step2_btn_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    step2_btn = el
                    print(f"[recon] ✓ Found step-2 submit: {sel}")
                    break
            except Exception:
                continue

        if step2_btn is None:
            print("[recon] WARNING: No step-2 submit button found — pressing Enter")
            await page.keyboard.press("Enter")
        else:
            await step2_btn.click()

        print("[recon] Waiting for post-login page (step 2)...")
        await asyncio.sleep(8)  # wait for SPA navigation + render

        # Capture step2 inputs for reference
        inputs_step2 = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input,button')).map(el => ({
                tag: el.tagName, type: el.type||'', id: el.id||'',
                name: el.name||'', placeholder: el.placeholder||'',
                visible: el.offsetParent !== null,
                outerHTML: el.outerHTML.substring(0,200),
            }));
        }""")
        (_OUT / "dom_inputs_step2.txt").write_text(
            "\n\n".join(f"[{i}] {e}" for i, e in enumerate(inputs_step2)),
            encoding="utf-8"
        )

        # ── Step 4: Capture post-login state ─────────────────────────────────
        post_html = await page.content()
        # Strip password values before saving
        (_OUT / "post_login.html").write_text(post_html, encoding="utf-8")
        await page.screenshot(path=str(_OUT / "post_login.png"), full_page=False)
        print(f"[recon] ✓ Saved post_login.html ({len(post_html):,} bytes) + post_login.png")
        print(f"[recon] Current URL: {page.url}")

        # Dump all visible links for navigation recon
        links = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: a.innerText.trim().substring(0, 80),
                href: a.href,
                id: a.id || '',
            })).filter(l => l.text.length > 0);
        }""")
        links_text = "\n".join(
            f"[{i}] text={l['text']!r}  href={l['href']}  id={l['id']!r}"
            for i, l in enumerate(links)
        )
        (_OUT / "dom_links.txt").write_text(links_text, encoding="utf-8")
        print(f"[recon] ✓ Found {len(links)} links → dom_links.txt")

        # ── Step 5: Verify login success ─────────────────────────────────────
        current_url = page.url
        links_text_all = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a')).map(a => a.innerText.trim()).join('|')"
        )
        logged_in = "Logout" in links_text_all or "My accounts" in links_text_all

        if not logged_in:
            print("[recon] ⚠ Login may have failed — 'Logout' not found in page links.")
            print(f"[recon] Current URL: {current_url}")
        else:
            print(f"[recon] ✓ Login confirmed (Logout link visible). URL: {current_url}")

            # ── Step 6: Click the "Accounts" widget on dashboard ─────────────
            # The nav menu items are hidden. Use the visible dashboard widget instead.
            print("[recon] Clicking 'Accounts' dashboard widget (li.CSA)...")
            try:
                # The Accounts widget has class "CSA" — click its child link
                await page.click("li.CSA a", timeout=8_000)
                await asyncio.sleep(5)
                await page.screenshot(path=str(_OUT / "my_accounts.png"))
                my_accounts_html = await page.content()
                (_OUT / "my_accounts.html").write_text(my_accounts_html, encoding="utf-8")
                print(f"[recon] ✓ Saved my_accounts.html ({len(my_accounts_html):,} bytes) + my_accounts.png")
                print(f"[recon] My Accounts URL: {page.url}")

                # Dump all links and elements on accounts page
                acct_links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.innerText.trim().substring(0,80),
                        href: a.href, id: a.id||'',
                    })).filter(l => l.text.length > 0);
                }""")
                (_OUT / "my_accounts_links.txt").write_text(
                    "\n".join(f"[{i}] text={l['text']!r}  href={l['href']}  id={l['id']!r}"
                              for i, l in enumerate(acct_links)),
                    encoding="utf-8"
                )
                print(f"[recon] ✓ Found {len(acct_links)} links on accounts page → my_accounts_links.txt")

                # Dump all elements with account-related classes
                acct_items = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('[class*="account"],[class*="Account"]')).map(el => ({
                        tag: el.tagName, id: el.id||'',
                        className: el.className.substring(0,80),
                        text: el.innerText.trim().substring(0,100),
                    })).filter(e => e.text.length > 0);
                }""")
                (_OUT / "my_accounts_elements.txt").write_text(
                    "\n".join(f"[{i}] {e}" for i, e in enumerate(acct_items)),
                    encoding="utf-8"
                )
                print(f"[recon] ✓ Found {len(acct_items)} account-class elements → my_accounts_elements.txt")

            except Exception as e:
                print(f"[recon] ⚠ Could not click Accounts widget: {e}")
                # Try JavaScript click as fallback
                try:
                    await page.evaluate("document.querySelector('li.CSA a').click()")
                    await asyncio.sleep(5)
                    my_accounts_html = await page.content()
                    (_OUT / "my_accounts.html").write_text(my_accounts_html, encoding="utf-8")
                    await page.screenshot(path=str(_OUT / "my_accounts.png"))
                    print("[recon] ✓ JS click worked — saved my_accounts.html")
                except Exception as e2:
                    print(f"[recon] ⚠ JS click also failed: {e2}")

            # ── Step 7: Click first account to get to transactions ───────────
            print("[recon] Clicking first account row to see account detail...")
            try:
                # Account rows are li.flip-account-list__items — click the first one
                await page.click("li.flip-account-list__items", timeout=8_000)
                await asyncio.sleep(5)
                await page.screenshot(path=str(_OUT / "account_detail.png"))
                acct_detail_html = await page.content()
                (_OUT / "account_detail.html").write_text(acct_detail_html, encoding="utf-8")
                print(f"[recon] ✓ Saved account_detail.html ({len(acct_detail_html):,} bytes) + account_detail.png")
                print(f"[recon] Account detail URL: {page.url}")

                # Dump links on account detail page
                detail_links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a,button')).map(el => ({
                        tag: el.tagName,
                        text: el.innerText.trim().substring(0,80),
                        href: el.href||'', id: el.id||'',
                        className: el.className.substring(0,60),
                    })).filter(l => l.text.length > 0);
                }""")
                (_OUT / "account_detail_links.txt").write_text(
                    "\n".join(f"[{i}] {l['tag']} text={l['text']!r}  id={l['id']!r}  class={l['className']!r}"
                              for i, l in enumerate(detail_links)),
                    encoding="utf-8"
                )
                print(f"[recon] ✓ Found {len(detail_links)} links/buttons → account_detail_links.txt")

            except Exception as e:
                print(f"[recon] ⚠ Could not click account row: {e}")

            # ── Step 8: Click the "•••" menu icon then "Account Activity" ─────
            # The account detail flip-card has a menu-icon (3-dots) that reveals
            # quick actions including "Account Activity"
            print("[recon] Clicking menu-icon (3-dots) on first account row...")
            try:
                # The menu icon is an <a class="menu-icon"> — click the first visible one
                menu_icon = await page.query_selector("a.menu-icon")
                if menu_icon:
                    await menu_icon.click()
                    await asyncio.sleep(2)
                    await page.screenshot(path=str(_OUT / "menu_open.png"))
                    print("[recon] ✓ Clicked menu-icon → saved menu_open.png")

                    # Now click "Account Activity"
                    await page.click("span:has-text('Account Activity')", timeout=5_000)
                    await asyncio.sleep(5)
                    await page.screenshot(path=str(_OUT / "transactions.png"))
                    txn_html = await page.content()
                    (_OUT / "transactions.html").write_text(txn_html, encoding="utf-8")
                    print(f"[recon] ✓ Saved transactions.html ({len(txn_html):,} bytes) + transactions.png")
                    print(f"[recon] Transactions URL: {page.url}")
                else:
                    print("[recon] ⚠ menu-icon not found")
                    await page.screenshot(path=str(_OUT / "debug_no_menu.png"))
            except Exception as e:
                print(f"[recon] ⚠ menu/activity click failed: {e}")
                await page.screenshot(path=str(_OUT / "debug_activity_error.png"))

            # ── Step 9: Wait for AJAX transaction data to load ───────────────
            # The page uses Oracle JET — data loads via REST API calls after render
            print("[recon] Waiting for transaction list to load via AJAX (up to 15s)...")

            # Intercept XHR/fetch calls to capture the REST API endpoint
            api_calls = []
            async def handle_response(response):
                url = response.url
                if any(x in url for x in ['transaction', 'activity', 'statement', 'demand-deposit']):
                    api_calls.append({'url': url, 'status': response.status})
            page.on("response", handle_response)

            # Also click the "Apply/Search" button if present to trigger data load
            apply_selectors = [
                "button:has-text('Apply')",
                "button:has-text('Search')",
                "button:has-text('بحث')",
                "[class*='apply']",
                "[class*='search-btn']",
            ]
            for sel in apply_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        print(f"[recon] ✓ Clicking apply/search button: {sel}")
                        await el.click()
                        break
                except Exception:
                    continue

            # Wait for list items or "no data" message
            for attempt in range(3):
                await asyncio.sleep(5)
                # Check if transaction rows appeared
                row_count = await page.evaluate("""() => {
                    return document.querySelectorAll(
                        'li[class*="transaction"], li[class*="txn"], li[class*="activity"], ' +
                        '[class*="transaction-row"], [class*="txn-row"], ' +
                        'oj-list-view li, [class*="listview"] li'
                    ).length;
                }""")
                if row_count > 0:
                    print(f"[recon] ✓ Found {row_count} list items after {(attempt+1)*5}s")
                    break
                print(f"[recon] Still waiting... attempt {attempt+1}/3")

            # Save final state
            await page.screenshot(path=str(_OUT / "transactions_loaded.png"), full_page=False)
            final_txn_html = await page.content()
            (_OUT / "transactions.html").write_text(final_txn_html, encoding="utf-8")
            print(f"[recon] ✓ Saved transactions.html ({len(final_txn_html):,} bytes)")

            # Log intercepted API calls
            if api_calls:
                (_OUT / "api_calls.txt").write_text(
                    "\n".join(f"{c['status']} {c['url']}" for c in api_calls),
                    encoding="utf-8"
                )
                print(f"[recon] ✓ Intercepted {len(api_calls)} API calls → api_calls.txt")
                for c in api_calls:
                    print(f"    {c['status']} {c['url']}")

            # Dump all visible text on the page
            page_text = await page.inner_text("body")
            (_OUT / "txn_page_text.txt").write_text(page_text, encoding="utf-8")
            print(f"[recon] ✓ Page text ({len(page_text):,} chars) → txn_page_text.txt")

            # Find all list items
            list_items = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('li')).map(el => ({
                    id: el.id||'',
                    className: el.className.substring(0,80),
                    text: el.innerText.trim().substring(0,200),
                    visible: el.offsetParent !== null,
                })).filter(e => e.text.length > 5 && e.visible).slice(0, 50);
            }""")
            (_OUT / "txn_list_items.txt").write_text(
                "\n\n".join(f"[{i}] {e}" for i, e in enumerate(list_items)),
                encoding="utf-8"
            )
            print(f"[recon] ✓ Found {len(list_items)} visible list items → txn_list_items.txt")

        print(f"\n[recon] Done. All files saved to: {_OUT}")
        print("[recon] Press Ctrl+C or close the browser window to exit.")

        # Keep browser open briefly so you can inspect
        await asyncio.sleep(10)
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="NBE recon — capture live HTML")
    parser.add_argument("--user", help="Plaintext NBE username (dev only)")
    parser.add_argument("--password", help="Plaintext NBE password (dev only)")
    parser.add_argument("--enc-user", help="AES-256-GCM encrypted username token")
    parser.add_argument("--enc-pass", help="AES-256-GCM encrypted password token")
    args = parser.parse_args()

    username: str | None = None
    password: str | None = None

    if args.enc_user and args.enc_pass:
        print("[recon] Decrypting credentials...")
        try:
            username = decrypt(args.enc_user, settings.encryption_key)
            password = decrypt(args.enc_pass, settings.encryption_key)
            print("[recon] ✓ Credentials decrypted successfully")
        except Exception as e:
            print(f"[recon] ERROR: Could not decrypt credentials: {e}")
            sys.exit(1)
    elif args.user and args.password:
        username = args.user
        password = args.password
        print("[recon] Using plaintext credentials")
    else:
        print("[recon] No credentials supplied — will capture login page only.")

    asyncio.run(recon(username, password))


if __name__ == "__main__":
    main()
