"""End-to-end pipeline tests with a faked scrape step (fully offline)."""

from __future__ import annotations

import pandas as pd
import pytest

import pipeline as pipeline_module
from data.models import ProductRecord
from pipeline import PipelineOutcome, init_database, run_pipeline

from .conftest import BASE_URL


class FakeScraper:
    """Replaces BooksToScrapeScraper; returns canned records."""

    def __init__(self, records, error: Exception | None = None):
        self._records = records
        self._error = error

    def scrape(self):
        if self._error:
            raise self._error
        return self._records


def make_record(i: int, price: float | None = None) -> ProductRecord:
    return ProductRecord(
        name=f"Product {i}",
        url=BASE_URL + f"catalogue/product-{i}/index.html",
        price=10.0 + i if price is None else price,
        currency="GBP",
        category="Travel",
        availability="In stock",
        rating=3,
        source_product_id=f"product-{i}",
    )


@pytest.fixture
def fake_scrape(monkeypatch, sample_records):
    """Patch pipeline's scraper class AND browser with offline fakes."""

    class DummyBrowserManager:
        def __init__(self, settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _install(records=None, error=None):
        records = sample_records if records is None else records
        monkeypatch.setattr(
            pipeline_module,
            "BooksToScrapeScraper",
            lambda settings, browser: FakeScraper(records, error),
        )
        monkeypatch.setattr(pipeline_module, "BrowserManager", DummyBrowserManager)

    return _install


def test_full_run_stores_and_reports(settings, fake_scrape):
    fake_scrape()
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "success"
    assert outcome.records_scraped == 4
    assert outcome.records_stored == 3  # duplicate URL dropped by cleaning
    assert outcome.csv_path is not None and outcome.csv_path.exists()
    assert outcome.excel_path is not None and outcome.excel_path.exists()
    assert outcome.analysis is not None and outcome.analysis.has_data


def test_second_run_updates_prices(settings, fake_scrape):
    """Re-scraping the same URLs updates rows in place instead of appending."""
    fake_scrape()
    run_pipeline(settings, configure_logging_=False)

    def updated(name, slug, price, rating):
        return ProductRecord(
            name=name,
            url=BASE_URL + f"catalogue/{slug}/index.html",
            price=price,
            currency="GBP",
            category="Travel",
            availability="In stock",
            rating=rating,
            source_product_id=slug,
        )

    fake_scrape(
        [
            updated("A Light in the Attic", "a-light-in-the-attic_1000", 48.0, 3),
            updated("Tipping the Velvet", "tipping-the-velvet_999", 53.74, 1),
            updated("Soumission", "soumission_998", 44.10, 4),
        ]
    )
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "success"
    from database.repository import ProductRepository

    repo = ProductRepository(settings.output.db_path)
    stored = repo.get_products()
    assert len(stored) == 3  # no growth on repeated runs

    prices = dict(zip(stored["name"], stored["price"]))
    assert float(prices["A Light in the Attic"]) == 48.0  # was 51.77
    assert float(prices["Soumission"]) == 44.10  # price absent in run 1
    assert float(prices["Tipping the Velvet"]) == 53.74  # unchanged

    previous = repo.get_previous_prices(outcome.run_id)
    # Baseline = run-1 observations that actually carried a price
    # (Soumission had none, so it cannot be compared).
    assert set(previous["source_product_id"]) == {
        "a-light-in-the-attic_1000",
        "tipping-the-velvet_999",
    }
    baseline = dict(
        zip(previous["source_product_id"], previous["previous_price"])
    )
    assert float(baseline["a-light-in-the-attic_1000"]) == 51.77


def test_new_product_on_later_run_is_inserted(settings, fake_scrape):
    """A genuinely new URL is added; existing rows are untouched."""
    fake_scrape()
    run_pipeline(settings, configure_logging_=False)

    fake_scrape([make_record(1)])
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "success"
    from database.repository import ProductRepository

    repo = ProductRepository(settings.output.db_path)
    stored = repo.get_products()
    assert len(stored) == 4
    assert "Product 1" in set(stored["name"])


def test_rejected_records_mark_run_partial(settings, fake_scrape):
    bad = ProductRecord(name="", url="also-bad")
    fake_scrape([make_record(1), bad])
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "partial"
    assert outcome.records_rejected == 1
    assert outcome.records_accepted == 1


def test_no_valid_records_is_no_data(settings, fake_scrape):
    bad = ProductRecord(name=None, url=None)
    fake_scrape([bad])
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "no_data"
    assert outcome.csv_path is None


def test_scraping_failure_is_reported(settings, fake_scrape):
    from utils.exceptions import PageFetchError

    fake_scrape(error=PageFetchError("site down"))
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "failed"
    assert "Scraping failed" in outcome.error


def test_excel_failure_preserves_database(settings, fake_scrape, monkeypatch):
    fake_scrape()

    def broken_excel(*args, **kwargs):
        from utils.exceptions import ReportGenerationError

        raise ReportGenerationError("disk full")

    monkeypatch.setattr(pipeline_module, "write_excel_report", broken_excel)
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "partial"
    assert outcome.csv_path is not None  # csv still produced
    from database.repository import ProductRepository

    assert ProductRepository(settings.output.db_path).count_products() == 3


def test_database_failure_does_not_claim_success(settings, fake_scrape, monkeypatch):
    fake_scrape()

    def broken_upsert(self, df, run_id):
        from utils.exceptions import DatabaseError

        raise DatabaseError("locked")

    monkeypatch.setattr(pipeline_module.ProductRepository, "upsert_products", broken_upsert)
    outcome = run_pipeline(settings, configure_logging_=False)
    assert outcome.status == "failed"
    assert "Database storage failed" in outcome.error
    assert outcome.csv_path is None  # reports never ran


def test_outcome_defaults():
    outcome = PipelineOutcome()
    assert outcome.ok is False


def test_init_database_creates_schema(settings):
    init_database(settings)
    assert settings.output.db_path.exists()
