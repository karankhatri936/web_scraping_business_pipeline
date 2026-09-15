"""Scraper tests: parsing + pagination wiring with offline fixture pages."""

from __future__ import annotations

import pytest

import scraper.scraper as scraper_module
from scraper.scraper import BooksToScrapeScraper

from .conftest import BASE_URL, CAT_URL, MYSTERY_URL, read_fixture


class FakeBrowserManager:
    """Satisfies the BrowserManager surface with a pre-rendered page."""

    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def new_page(self):
        return self._page


@pytest.fixture
def offline_scraper(settings, page_factory, monkeypatch):
    """Scraper whose page loads are served from local fixtures.

    Scoped to a single category: ``settings`` allows two categories, but the
    fixture map below only provides pages for the first one, so the scraper
    settings are narrowed to mirror the fixture map.
    """
    fixture_pages = {
        BASE_URL: read_fixture("category_page.html"),
        CAT_URL: read_fixture("category_page.html"),
        CAT_URL.replace("index.html", "page-2.html"): read_fixture(
            "category_last_page.html"
        ),
    }
    rendered: dict[str, object] = {}

    def fake_load(self, page, url):
        if url not in rendered:
            rendered[url] = page_factory(fixture_pages[url])
        return rendered[url]

    monkeypatch.setattr(BooksToScrapeScraper, "_load_page", fake_load)
    page = page_factory(read_fixture("category_page.html"))
    browser = FakeBrowserManager(page)
    one_category = type(settings.scraper)(
        base_url=BASE_URL,
        request_delay_seconds=0.0,
        page_load_retries=0,
        max_pages_per_category=2,
        max_categories=1,
    )
    return BooksToScrapeScraper(one_category, browser)


def test_scrape_collects_and_deduplicates(offline_scraper):
    records = offline_scraper.scrape()
    # 3 products on page 1 + 1 on page 2; the malformed card is an error
    assert len(records) == 4
    stats = offline_scraper.stats
    assert stats.parser_errors == 1
    assert stats.pages_visited == 2
    assert stats.categories_scraped == 1
    urls = [r.url for r in records]
    assert len(urls) == len(set(urls))
    assert stats.records_scraped == 4


def test_scrape_respects_category_limit(settings, offline_scraper):
    """The category limit truncates the discovered category list."""
    offline_scraper.scrape()
    assert offline_scraper.stats.categories_found == 2
    assert offline_scraper.stats.categories_scraped == 1


def test_scrape_respects_product_limit(settings, page_factory, monkeypatch):
    """Reaching the product limit stops the walk (no further page requests)."""
    fixture_pages = {
        BASE_URL: read_fixture("category_page.html"),
        CAT_URL: read_fixture("category_page.html"),
    }
    requested: list[str] = []

    def fake_load(self, page, url):
        requested.append(url)
        return page_factory(fixture_pages[url])

    monkeypatch.setattr(BooksToScrapeScraper, "_load_page", fake_load)
    limited = type(settings.scraper)(
        base_url=BASE_URL,
        request_delay_seconds=0.0,
        page_load_retries=0,
        max_categories=0,
        max_products=2,
    )
    scraper = BooksToScrapeScraper(
        limited, FakeBrowserManager(page_factory(read_fixture("category_page.html")))
    )
    records = scraper.scrape()
    assert len(records) == 2
    page_two = CAT_URL.replace("index.html", "page-2.html")
    assert page_two not in requested


def test_in_run_duplicate_detection(settings, page_factory, monkeypatch):
    """Two categories serving identical products must not double-count."""
    fixture_pages = {
        BASE_URL: read_fixture("category_page.html"),
        CAT_URL: read_fixture("category_page.html"),
        CAT_URL.replace("index.html", "page-2.html"): read_fixture(
            "category_last_page.html"
        ),
        MYSTERY_URL: read_fixture("category_page.html"),
        MYSTERY_URL.replace("index.html", "page-2.html"): read_fixture(
            "category_last_page.html"
        ),
    }
    rendered: dict[str, object] = {}

    def fake_load(self, page, url):
        if url not in rendered:
            rendered[url] = page_factory(fixture_pages[url])
        return rendered[url]

    monkeypatch.setattr(BooksToScrapeScraper, "_load_page", fake_load)
    two_cats = type(settings.scraper)(
        base_url=BASE_URL,
        request_delay_seconds=0.0,
        page_load_retries=0,
        max_pages_per_category=2,
        max_categories=2,
    )
    scraper = BooksToScrapeScraper(
        two_cats, FakeBrowserManager(page_factory(read_fixture("category_page.html")))
    )
    records = scraper.scrape()
    # each category serves the same 3 + 1 products -> 4 duplicates in total
    assert len(records) == 4
    assert scraper.stats.duplicates_in_run == 4
    assert scraper.stats.categories_scraped == 2
    assert scraper.stats.pages_visited == 4


def test_missing_categories_raise(settings, page_factory, monkeypatch):
    def fake_load(self, page, url):
        return page_factory("<html><body><div id='x'></div></body></html>")

    monkeypatch.setattr(BooksToScrapeScraper, "_load_page", fake_load)
    scraper = BooksToScrapeScraper(
        settings.scraper, FakeBrowserManager(page_factory("<html></html>"))
    )
    from utils.exceptions import PageFetchError

    with pytest.raises(PageFetchError):
        scraper.scrape()


def test_robots_disallowed_raises(settings, monkeypatch):
    """A disallowing robots.txt must abort the run before scraping."""
    from urllib import robotparser

    class DisallowingParser:
        def set_url(self, url):
            pass

        def read(self):
            pass

        def can_fetch(self, user_agent, url):
            return False

    monkeypatch.setattr(scraper_module.robotparser, "RobotFileParser", DisallowingParser)
    from utils.exceptions import RobotsDisallowedError

    scraper = BooksToScrapeScraper(
        type(settings.scraper)(
            base_url=BASE_URL, respect_robots=True, request_delay_seconds=0.0
        ),
        FakeBrowserManager(None),
    )
    with pytest.raises(RobotsDisallowedError):
        scraper.scrape()
