"""
tools/browser.py
Playwright async browser factory with anti-detection and persistent session support.
"""
import asyncio
import random
import json
from pathlib import Path
from typing import Optional
from loguru import logger
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)
from config.settings import SESSION_PATH, HEADLESS, SLOW_MO


# ─── Human-like delay ─────────────────────────────────────────────────────────

async def human_delay(min_ms: float = 800, max_ms: float = 2500) -> None:
    """Randomized delay to mimic human interaction timing."""
    delay = random.uniform(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


async def human_type(page: Page, selector: str, text: str, delay_ms: int = 80) -> None:
    """Type text character by character with random timing."""
    await page.click(selector)
    await human_delay(200, 400)
    await page.type(selector, text, delay=delay_ms + random.randint(-20, 40))


# ─── Browser Factory ──────────────────────────────────────────────────────────

class BrowserManager:
    """
    Manages a persistent Playwright browser context.
    Saves/restores session so login is skipped on restarts.
    Safe to call close() / save_session() multiple times.
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._closed: bool = False   # Guard against double-close

    async def start(self) -> BrowserContext:
        """Launch browser and restore session if available."""
        self._playwright = await async_playwright().start()

        # Launch Chromium with stealth args
        self._browser = await self._playwright.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-web-security",
                "--disable-dev-shm-usage",
                "--lang=en-US,en;q=0.9",
            ],
        )

        # Load saved session or start fresh
        session_file = Path(SESSION_PATH)
        storage_state = str(session_file) if session_file.exists() else None

        self._context = await self._browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        # Inject stealth JS to remove navigator.webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        if storage_state:
            logger.info("✅ Restored browser session from disk")
        else:
            logger.info("🆕 Starting fresh browser session")

        return self._context

    async def new_page(self) -> Page:
        """Open a new page in the current context."""
        if not self._context:
            await self.start()
        page = await self._context.new_page()
        return page

    async def save_session(self) -> None:
        """Save cookies and storage state to disk for reuse."""
        if self._closed or not self._context:
            return
        try:
            await self._context.storage_state(path=str(SESSION_PATH))
            logger.info(f"💾 Session saved to {SESSION_PATH}")
        except Exception as e:
            logger.warning(f"Could not save session (context may be closing): {e}")

    async def close(self) -> None:
        """Save session and close browser. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        await self.save_session()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("🔒 Browser closed")


# ─── Singleton ────────────────────────────────────────────────────────────────
browser_manager = BrowserManager()
