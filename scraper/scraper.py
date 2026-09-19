"""Scraper implementation for books.toscrape.com.

Responsibilities (and nothing else):
* robots.txt pre-flight check (policy only - no bypassing of any control)
* discovering category listing pages
* loading pages with a politeness delay and bounded retries
* coordinating the pagination walker + HTML parser
* de-duplicating records inside a single run

Database, cleaning, analytics and reporting live in their own packages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import playwright.sync_api as pw

from config import ScraperSettings
from data.models import ProductRecord
from scraper.browser import BrowserManager
from scraper.pagination import PageWalkResult, walk_pages
from scraper.parsers import Category, parse_categories, parse_next_href, parse_products
from utils.exceptions import PageFetchError, RobotsDisallowedError
from utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = "web-scraping-business-pipeline/1.0 (respectful demo scraper)"


@dataclass
class ScrapeStats:
    """Counters describing one scraping run."""

    categories_found: int = 0
    categories_scraped: int = 0
    pages_visited: int = 0
    pages_failed: int = 0
    parser_errors: int = 0
    duplicates_in_run: int = 0
    records_scraped: int = 0
    walk_results: list[PageWalkResult] = field(default_factory=list)


class BooksToScrapeScraper:
    """Collects product records from the public books.toscrape.com sandbox."""

    source_name = "books.toscrape.com"

    def __init__(self, settings: ScraperSettings, browser: BrowserManager) -> None:
        self._settings = settings
        self._browser = browser
        self._records: list[ProductRecord] = []
        self._seen_urls: set[str] = set()
        self._seen_ids: set[str] = set()
        self.stats = ScrapeStats()

    # -- public API ---------------------------------------------------------
    def scrape(self) -> list[ProductRecord]:
        """Scrape categories (subject to limits) and return product records."""
        base_url = self._settings.base_url
        self._check_robots(base_url)

        page = self._browser.new_page()
        logger.info("Scraping started: %s", base_url)
        categories = self._load_categories(page, base_url)
        self.stats.categories_found = len(categories)

        max_categories = self._settings.max_categories
        selected = categories[:max_categories] if max_categories else categories
        logger.info(
            "Scraping %d of %d categories (limit=%s)",
            len(selected),
            len(categories),
            max_categories or "none",
        )

        for category in selected:
            if self._product_limit_reached():
                logger.info("Product limit reached; stopping category loop")
                break
            self._scrape_category(page, category)
            self.stats.categories_scraped += 1

        self.stats.records_scraped = len(self._records)
        logger.info(
            "Scraping finished: %d record(s), %d page(s) visited, "
            "%d page(s) failed, %d parser error(s), %d in-run duplicate(s)",
            len(self._records),
            self.stats.pages_visited,
            self.stats.pages_failed,
            self.stats.parser_errors,
            self.stats.duplicates_in_run,
        )
        return self._records

    # -- robots -------------------------------------------------------------
    def _check_robots(self, base_url: str) -> None:
        """Refuse to scrape when robots.txt disallows the listing paths."""
        if not self._settings.respect_robots:
            logger.info("robots.txt check disabled by configuration")
            return
        parser = robotparser.RobotFileParser()
        robots_url = urljoin(base_url, "/robots.txt")
        parser.set_url(robots_url)
        try:
            parser.read()
        except OSError as exc:
            # No readable robots.txt: the sandbox site sets no restrictions.
            logger.warning("Could not read %s (%s); assuming allowed", robots_url, exc)
            return
        listing = urljoin(base_url, "/catalogue/category/books/travel_2/index.html")
        if not parser.can_fetch(_USER_AGENT, listing):
            raise RobotsDisallowedError(
                f"robots.txt of {urlparse(base_url).netloc} disallows scraping "
                "the catalog listing pages"
            )
        logger.info("robots.txt check passed for %s", urlparse(base_url).netloc)

    # -- page loading -------------------------------------------------------
    def _load_page(self, page: pw.Page, url: str) -> pw.Page | None:
        """Navigate to *url* with a politeness delay and bounded retries."""
        time.sleep(self._settings.request_delay_seconds)
        attempts = self._settings.page_load_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                page.goto(url, wait_until="domcontentloaded")
                return page
            except pw.TimeoutError as exc:
                logger.warning(
                    "Timeout on %s (attempt %d/%d): %s", url, attempt, attempts, exc
                )
            except pw.Error as exc:
                logger.warning(
                    "Navigation error on %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    attempts,
                    exc,
                )
        logger.error("Giving up on %s after %d attempt(s)", url, attempts)
        return None

    # -- category discovery -------------------------------------------------
    def _load_categories(self, page: pw.Page, base_url: str) -> list[Category]:
        """Load the home page and extract the category listing links."""
        loaded = self._load_page(page, base_url)
        if loaded is None:
            raise PageFetchError(
                f"Could not load the category overview page: {base_url}"
            )
        categories = parse_categories(loaded, base_url)
        if not categories:
            raise PageFetchError(
                "No categories found on the overview page - the site layout "
                "may have changed"
            )
        return categories

    # -- one category -------------------------------------------------------
    def _scrape_category(self, page: pw.Page, category: Category) -> None:
        logger.info("Scraping category %r: %s", category.name, category.url)

        def visitor(url: str, loaded_page: pw.Page) -> bool:
            records, errors = parse_products(loaded_page, category.name, url)
            self.stats.parser_errors += len(errors)
            for record in records:
                self._add_record(record)
            # Returning False stops the walk so no further pages are requested
            # once the product limit is satisfied.
            return not self._product_limit_reached()

        result = walk_pages(
            start_url=category.url,
            loader=lambda url: self._load_page(page, url),
            visitor=visitor,
            next_href=parse_next_href,
            max_pages=self._settings.max_pages_per_category,
        )
        self.stats.walk_results.append(result)
        self.stats.pages_visited += len(result.pages_visited)
        self.stats.pages_failed += len(result.pages_failed)

    # -- record accumulation ------------------------------------------------
    def _add_record(self, record: ProductRecord) -> None:
        """Append a record, dropping in-run duplicates (same URL or same ID)."""
        if self._product_limit_reached():
            return
        url_key = record.url.split("#", 1)[0]
        id_key = record.source_product_id
        if url_key in self._seen_urls or (id_key and id_key in self._seen_ids):
            self.stats.duplicates_in_run += 1
            logger.debug("Skipping duplicate record: %s", record.name)
            return
        self._seen_urls.add(url_key)
        if id_key:
            self._seen_ids.add(id_key)
        self._records.append(record)

    def _product_limit_reached(self) -> bool:
        limit = self._settings.max_products
        return bool(limit) and len(self._records) >= limit

