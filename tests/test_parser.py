"""Tests for books.toscrape.com parsing (offline via set_content)."""

from __future__ import annotations

import pytest

from scraper.parsers import (
    extract_source_id,
    parse_categories,
    parse_next_href,
    parse_price,
    parse_products,
    parse_rating,
)

from .conftest import BASE_URL, CAT_URL, read_fixture


def test_parse_price_variants():
    assert parse_price("£51.77") == (51.77, "GBP")
    assert parse_price("£1,052.15") == (1052.15, "GBP")
    assert parse_price("$19.99") == (19.99, "USD")
    assert parse_price("€8.00") == (8.0, "EUR")
    # The source site uses dot decimals; a comma is treated as a thousands
    # separator, so European-style "8,00" is out of contract.
    assert parse_price("€8,00") == (800.0, "EUR")
    assert parse_price("Free") == (None, None)
    assert parse_price("") == (None, None)
    assert parse_price("£") == (None, None)


def test_parse_rating_variants():
    assert parse_rating("star-rating Three") == 3
    assert parse_rating("star-rating Five") == 5
    assert parse_rating("star-rating One") == 1
    assert parse_rating("star-rating") is None
    assert parse_rating(None) is None


def test_extract_source_id():
    url = BASE_URL + "catalogue/a-light-in-the-attic_1000/index.html"
    assert extract_source_id(url) == "a-light-in-the-attic_1000"


def test_parse_products_from_fixture(page_factory):
    page = page_factory(read_fixture("category_page.html"))
    records, errors = parse_products(page, "Travel", CAT_URL)
    assert len(errors) == 1  # the malformed card
    assert len(records) == 3
    first = records[0]
    assert first.name == "A Light in the Attic"
    assert first.url == BASE_URL + "catalogue/a-light-in-the-attic_1000/index.html"
    assert first.price == 51.77
    assert first.currency == "GBP"
    assert first.category == "Travel"
    assert first.availability == "In stock"
    assert first.rating == 3
    assert first.source_product_id == "a-light-in-the-attic_1000"
    assert first.image_url is not None and first.image_url.startswith("https://")
    # out of stock product
    assert records[2].availability == "Out of stock"
    assert records[2].rating == 4
    # scraped_at stamped automatically
    assert first.scraped_at


def test_parse_products_missing_optional_fields_are_none(page_factory):
    page = page_factory(read_fixture("category_page.html"))
    records, _ = parse_products(page, "Travel", CAT_URL)
    assert all(r.price is not None for r in records)


def test_parse_next_href(page_factory):
    first = page_factory(read_fixture("category_page.html"))
    assert parse_next_href(first) == "page-2.html"
    last = page_factory(read_fixture("category_last_page.html"))
    assert parse_next_href(last) is None


def test_parse_categories(page_factory):
    page = page_factory(read_fixture("category_page.html"))
    categories = parse_categories(page, BASE_URL)
    names = [c.name for c in categories]
    assert "Travel" in names and "Mystery" in names
    assert all("books_1" not in c.url for c in categories)  # all-products excluded
    travel = next(c for c in categories if c.name == "Travel")
    assert travel.url == CAT_URL


def test_parse_products_on_last_page(page_factory):
    page = page_factory(read_fixture("category_last_page.html"))
    records, errors = parse_products(page, "Travel", CAT_URL)
    assert errors == []
    assert records[0].name == "The Black Maria"
    assert records[0].price == 1052.15  # thousands separator handled


def test_parse_products_on_empty_page(page_factory):
    page = page_factory(read_fixture("empty_page.html"))
    records, errors = parse_products(page, "Travel", CAT_URL)
    assert records == []
    assert errors == []
