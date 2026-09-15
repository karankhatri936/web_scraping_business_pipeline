"""Shared pytest fixtures.

Unit tests are fully deterministic and offline: Playwright pages are created
locally via ``set_content`` (no network), databases live in tmp_path, and the
scrape step is faked at the pipeline level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import OutputSettings, SchedulerSettings, ScraperSettings, Settings
from data.models import ProductRecord

FIXTURES = Path(__file__).parent / "fixtures"

BASE_URL = "https://books.toscrape.com/"
CAT_URL = BASE_URL + "catalogue/category/books/travel_2/index.html"
MYSTERY_URL = BASE_URL + "catalogue/category/books/mystery_3/index.html"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Pipeline settings pointing every artefact into tmp_path, zero delay."""
    return Settings(
        scraper=ScraperSettings(
            base_url=BASE_URL,
            headless=True,
            navigation_timeout_seconds=10,
            request_delay_seconds=0.0,
            page_load_retries=0,
            max_pages_per_category=2,
            max_categories=2,
            max_products=0,
            respect_robots=False,
        ),
        output=OutputSettings(
            db_path=tmp_path / "test_products.db",
            output_csv_dir=tmp_path / "csv",
            output_excel_dir=tmp_path / "excel",
            log_dir=tmp_path / "logs",
            log_level="WARNING",
            report_top_n=5,
        ),
        scheduler=SchedulerSettings(interval_minutes=60, max_runs=0),
    )


@pytest.fixture
def sample_records() -> list[ProductRecord]:
    return [
        ProductRecord(
            name="A Light in the Attic",
            url=BASE_URL + "catalogue/a-light-in-the-attic_1000/index.html",
            price=51.77,
            currency="GBP",
            category="Travel",
            availability="In stock",
            rating=3,
            image_url=BASE_URL + "media/cache/2c/da/2c.jpg",
            source_product_id="a-light-in-the-attic_1000",
        ),
        ProductRecord(
            name="Tipping the Velvet",
            url=BASE_URL + "catalogue/tipping-the-velvet_999/index.html",
            price=53.74,
            currency="GBP",
            category="Travel",
            availability="In stock",
            rating=1,
            image_url=BASE_URL + "media/cache/33/cf/33cf.jpg",
            source_product_id="tipping-the-velvet_999",
        ),
        # duplicate URL of the first record (different price -> later run)
        ProductRecord(
            name="A Light in the Attic",
            url=BASE_URL + "catalogue/a-light-in-the-attic_1000/index.html",
            price=49.99,
            currency="GBP",
            category="Travel",
            availability="In stock",
            rating=3,
            source_product_id="a-light-in-the-attic_1000",
        ),
        # minimal record: optional fields missing
        ProductRecord(
            name="Soumission",
            url=BASE_URL + "catalogue/soumission_998/index.html",
            source_product_id="soumission_998",
        ),
    ]


@pytest.fixture(scope="session")
def page_factory():
    """Render HTML strings into real (offline) Chromium pages."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context()
    pages: list = []

    def factory(html: str):
        page = context.new_page()
        page.set_content(html)
        pages.append(page)
        return page

    yield factory
    for page in pages:
        page.close()
    context.close()
    browser.close()
    pw.stop()
