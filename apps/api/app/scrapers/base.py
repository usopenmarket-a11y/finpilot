"""Abstract base scraper for FinPilot bank scrapers.

All bank-specific scrapers inherit from ``BankScraper``.  The base class owns:
- Playwright browser lifecycle (launch, context configuration, teardown)
- Anti-detection hardening (user-agent, viewport jitter, webdriver flag removal)
- Human-like interaction helpers (randomised delays, character-by-character typing)
- Screenshot-on-failure helper (never captures login forms)
- Account-number masking for safe logging
- Shared custom exception hierarchy

Credentials are accepted as plaintext strings.  The router layer is responsible
for decryption before calling the scraper.  The scraper MUST NOT log credentials
under any circumstances; use ``***`` as a placeholder in all log messages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from app.models.db import BankAccount, Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Screenshot output directory — ephemeral, never commit to source control
# ---------------------------------------------------------------------------
_DEBUG_DIR = Path("/tmp/finpilot_debug")

# ---------------------------------------------------------------------------
# Playwright browser path — ensure PLAYWRIGHT_BROWSERS_PATH is set so
# Playwright finds the browsers installed during the Render build step.
# The Render build command installs to /opt/render/project/src/.playwright-browsers
# but Playwright's default cache is /opt/render/.cache/ms-playwright (missing
# at runtime on Render free tier).  Set the env var defensively here so any
# process that imports this module has it configured before async_playwright().
# ---------------------------------------------------------------------------
_RENDER_BROWSERS_PATH = "/opt/render/project/src/.playwright-browsers"
if os.path.isdir(_RENDER_BROWSERS_PATH) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _RENDER_BROWSERS_PATH
    logger.debug("base: set PLAYWRIGHT_BROWSERS_PATH=%s (Render fallback)", _RENDER_BROWSERS_PATH)


# ---------------------------------------------------------------------------
# Realistic Chrome user-agent pool
# ---------------------------------------------------------------------------
_USER_AGENTS: list[str] = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
]


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class ScraperException(Exception):
    """Root of the scraper exception hierarchy.

    All subclasses carry a ``bank_code`` and ``timestamp`` so callers can
    correlate errors across log lines without any sensitive context.
    """

    def __init__(self, message: str, bank_code: str) -> None:
        super().__init__(message)
        self.bank_code = bank_code
        self.timestamp = time.time()


class ScraperLoginError(ScraperException):
    """Raised when the bank portal rejects the supplied credentials."""


class ScraperTimeoutError(ScraperException):
    """Raised when a Playwright wait operation exceeds its deadline."""


class ScraperParseError(ScraperException):
    """Raised when the scraped HTML does not match the expected structure."""


class ScraperOTPRequired(ScraperException):
    """Raised when the portal demands an OTP before proceeding.

    The ``session_token`` field carries an opaque reference that the API layer
    uses to resume the scrape session once the user submits the OTP via the
    ``/scrapers/otp`` endpoint.
    """

    def __init__(self, message: str, bank_code: str, session_token: str) -> None:
        super().__init__(message, bank_code)
        self.session_token = session_token


class ScraperPasswordChangeRequired(ScraperException):
    """Raised when the bank portal forces the user to change their password before proceeding."""


class BankPortalUnreachableError(ScraperException):
    """Raised when the bank portal returns a network-level error or 5xx."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ScraperResult:
    """Container returned by every successful ``BankScraper.scrape()`` call.

    ``accounts`` contains one ``BankAccount`` per bank account discovered
    during the scrape (e.g. savings EGP, current EGP, savings USD, payroll).
    All fields except ``id``, ``user_id``, ``created_at``, and ``updated_at``
    are populated by the scraper; the pipeline layer fills in the remainder
    before persisting.

    ``transactions`` are raw-scraped objects from ALL accounts combined.
    Each ``Transaction`` carries the ``account_number_masked`` of its source
    account via ``raw_data["account_number_masked"]`` so the pipeline can
    route each transaction to the correct ``account_id`` after upsert.

    ``raw_html`` maps a descriptive page label (e.g. ``"dashboard"``,
    ``"transactions_0"``) to the full HTML string captured for that page.
    Used for debugging and re-processing without re-scraping.
    """

    accounts: list[BankAccount]
    transactions: list[Transaction] = field(default_factory=list)
    raw_html: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Backward-compatibility shim
    # ------------------------------------------------------------------

    @property
    def account(self) -> BankAccount:
        """Return the primary (first) account.

        Retained for backward compatibility with callers that still access
        ``result.account`` rather than ``result.accounts[0]``.  New code
        should iterate ``result.accounts`` directly.

        Raises:
            IndexError: If ``accounts`` is empty (should not happen on a
                successful scrape).
        """
        return self.accounts[0]


# ---------------------------------------------------------------------------
# Abstract base scraper
# ---------------------------------------------------------------------------


class BankScraper(ABC):
    """Abstract base class for all FinPilot bank scrapers.

    Subclasses must:
    1. Set the ``bank_name`` class variable to the canonical bank code
       (``"NBE"``, ``"CIB"``, ``"BDC"``, ``"UB"``).
    2. Implement ``scrape()`` to return a ``ScraperResult``.

    Credentials are stored as private instance attributes and must NEVER appear
    in log output.  All log messages that reference credentials must use ``***``
    as a placeholder.
    """

    bank_name: ClassVar[str]

    def __init__(self, username: str, password: str) -> None:
        # Store credentials as private attributes; never expose in __repr__,
        # __str__, or any log statement.
        self._username: str = username
        self._password: str = password

    def __repr__(self) -> str:
        # Deliberately omit credentials from repr.
        return f"<{self.__class__.__name__} username=***>"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self) -> ScraperResult:
        """Execute the full scrape cycle and return structured results.

        Implementations must:
        - Call ``_launch_browser`` / ``_close_browser`` via a try/finally.
        - Raise ``ScraperLoginError`` on bad credentials.
        - Raise ``ScraperTimeoutError`` on Playwright timeout.
        - Raise ``ScraperParseError`` on unexpected HTML structure.
        - Call ``_safe_screenshot`` before raising any exception that occurs
          AFTER login (post-login pages only — never screenshot login forms).
        """

    # ------------------------------------------------------------------
    # Browser lifecycle helpers
    # ------------------------------------------------------------------

    async def _launch_browser(self) -> tuple[Browser, BrowserContext, Page]:
        """Launch headless Chromium with anti-detection hardening.

        Returns:
            A 3-tuple of ``(Browser, BrowserContext, Page)``.  The caller is
            responsible for closing the browser via ``_close_browser``.

        Anti-detection measures applied:
        - ``navigator.webdriver`` property spoofed to ``undefined``
        - Randomised realistic viewport (1280–1920 × 800–1080)
        - Random Chrome user-agent from ``_USER_AGENTS``
        - ``--disable-blink-features=AutomationControlled`` launch flag
        - ``user-agent`` and ``accept-language`` headers set on every request
        """
        playwright = await async_playwright().start()
        self._playwright = playwright  # keep reference for teardown

        viewport_width = random.randint(1280, 1920)
        viewport_height = random.randint(800, 1080)
        user_agent = random.choice(_USER_AGENTS)

        browser: Browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                # Memory reduction for Render free tier (512 MB RAM limit)
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--hide-scrollbars",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
                "--js-flags=--max-old-space-size=128",
                "--renderer-process-limit=1",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )

        context: BrowserContext = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=user_agent,
            locale="en-US",
            timezone_id="Africa/Cairo",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            },
        )

        # Remove the ``navigator.webdriver`` property that headless Chrome sets.
        # This is the single most reliable bot-detection signal.
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'ar'],
            });
            """
        )

        page: Page = await context.new_page()

        logger.debug(
            "%s browser launched — viewport=%dx%d ua=%s",
            self.bank_name,
            viewport_width,
            viewport_height,
            user_agent[:40] + "...",
        )

        return browser, context, page

    async def _close_browser(self, browser: Browser) -> None:
        """Gracefully close the browser and the underlying Playwright instance.

        Safe to call even if the browser is already closed.
        """
        try:
            await browser.close()
        except Exception as exc:
            logger.debug("%s browser close error (ignored): %s", self.bank_name, exc)

        playwright = getattr(self, "_playwright", None)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                logger.debug("%s playwright stop error (ignored): %s", self.bank_name, exc)
            self._playwright = None

    # ------------------------------------------------------------------
    # Human-like interaction helpers
    # ------------------------------------------------------------------

    async def _random_delay(self, min_s: float = 2.0, max_s: float = 5.0) -> None:
        """Sleep for a random duration between ``min_s`` and ``max_s`` seconds.

        Called between page navigation events and before clicking interactive
        elements to mimic natural human pacing.

        In test mode (``APP_ENV=test``) the sleep is skipped entirely so that
        unit tests remain fast and deterministic without requiring the callers
        to mock ``asyncio.sleep``.
        """
        if os.environ.get("APP_ENV") == "test":
            return
        delay = random.uniform(min_s, max_s)
        logger.debug("%s random delay %.2fs", self.bank_name, delay)
        await asyncio.sleep(delay)

    async def _type_human(self, page: Page, selector: str, text: str) -> None:
        """Click a field and type ``text`` character-by-character with micro-delays.

        Each keystroke fires with a random delay of 80–180 ms to approximate
        realistic typing rhythm.  This avoids the instantaneous fill that
        ``page.fill()`` performs, which some portals detect as automation.

        Args:
            page: The active Playwright page.
            selector: CSS selector for the target input element.
            text: The text to type.  Must not be logged by callers.
        """
        await page.click(selector)
        for char in text:
            await page.keyboard.type(char, delay=random.uniform(80, 180))

    # ------------------------------------------------------------------
    # Screenshot helper (post-auth pages only)
    # ------------------------------------------------------------------

    async def _safe_screenshot(
        self, page: Page, label: str, full_page: bool = False
    ) -> Path | None:
        """Capture a debug screenshot and return its path.

        This helper MUST only be called on post-authentication pages.  NEVER
        call it while a login form is visible — credentials could be captured.

        The screenshot file is written to ``/tmp/finpilot_debug/`` which is
        ephemeral and never persisted to source control or object storage.

        Args:
            page: The active Playwright page.
            label: Short descriptive label used in the filename.
            full_page: Whether to capture the full scrollable page (default
                ``False`` to avoid accidentally capturing sensitive content
                scrolled out of view).

        Returns:
            The ``Path`` of the written screenshot, or ``None`` if the
            screenshot itself fails.
        """
        try:
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
            path = _DEBUG_DIR / f"{self.bank_name}_{safe_label}_{int(time.time())}.png"
            await page.screenshot(path=str(path), full_page=full_page)
            logger.error("%s debug screenshot saved: %s", self.bank_name, path)
            return path
        except Exception as exc:
            logger.warning("%s screenshot failed: %s", self.bank_name, exc)
            return None

    # ------------------------------------------------------------------
    # Account number masking
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_account_number(raw: str) -> str:
        """Return a masked account string showing only the last 4 digits.

        Examples::

            >>> BankScraper._mask_account_number("1234567890")
            '****7890'
            >>> BankScraper._mask_account_number("1234")
            '****1234'
            >>> BankScraper._mask_account_number("12")
            '****12'

        Args:
            raw: The full account number string (digits and/or hyphens).

        Returns:
            A string in the format ``****XXXX`` where ``XXXX`` is the last
            four characters of ``raw``.
        """
        digits_only = "".join(c for c in raw if c.isdigit())
        tail = digits_only[-4:] if len(digits_only) >= 4 else digits_only
        return f"****{tail}"
