"""Playwright browser lifecycle management.

Encapsulates Playwright start-up/tear-down so callers never touch raw
Playwright objects for resource handling. Always use as a context manager::

    with BrowserManager(settings) as browser:
        page = browser.new_page()
        page.goto("https://example.com")

The manager guarantees that the page, browser context, browser and Playwright
driver are closed even when scraping code raises an exception.
"""

from __future__ import annotations

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from config import ScraperSettings
from utils.exceptions import BrowserError
from utils.logger import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """Owns the Playwright instance, browser and context for one pipeline run."""

    def __init__(self, settings: ScraperSettings) -> None:
        self._settings = settings
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._closed = False

    # -- context manager protocol ------------------------------------------
    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False  # never swallow exceptions

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Start Playwright and launch the browser (idempotent)."""
        if self._browser is not None:
            return
        try:
            logger.info(
                "Starting Chromium (headless=%s)",
                self._settings.headless,
            )
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self._settings.headless,
            )
            self._context = self._browser.new_context(
                locale="en-GB",
                viewport={"width": 1366, "height": 900},
            )
            self._context.set_default_timeout(
                self._settings.navigation_timeout_seconds * 1000
            )
            self._context.set_default_navigation_timeout(
                self._settings.navigation_timeout_seconds * 1000
            )
            logger.info("Browser started")
        except Exception as exc:  # noqa: BLE001 - re-raised as domain error
            self.close()
            raise BrowserError(f"Failed to start the browser: {exc}") from exc

    def new_page(self) -> Page:
        """Create a new page inside the managed context."""
        if self._context is None:
            raise BrowserError("Browser not started - use 'with BrowserManager(...)'")
        try:
            return self._context.new_page()
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Failed to create a browser page: {exc}") from exc

    def close(self) -> None:
        """Close page context, browser and Playwright driver (idempotent)."""
        if self._closed:
            return
        self._closed = True
        for resource, closer in (
            ("browser context", lambda: self._context.close()),
            ("browser", lambda: self._browser.close()),
            ("playwright driver", lambda: self._playwright.stop()),
        ):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 - cleanup must continue
                logger.warning("Error while closing %s: %s", resource, exc)
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser resources released")

    @property
    def is_running(self) -> bool:
        return self._browser is not None
