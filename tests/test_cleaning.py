"""Tests for the pandas cleaning and transformation layers."""

from __future__ import annotations

import pandas as pd

from data.cleaner import CleanResult, clean_products, records_to_dataframe
from data.transformer import add_derived_columns


def test_records_to_dataframe_shape(sample_records):
    df = records_to_dataframe(sample_records)
    assert list(df.columns)[:2] == ["name", "url"]
    assert len(df) == 4


def test_whitespace_normalisation():
    df = records_to_dataframe(
        [{"name": "  Spaced   Out  ", "url": "  https://example.com/x  ",
          "availability": "  In   stock ", "source_product_id": "  x_1 "}]
    )
    result = clean_products(df)
    row = result.frame.iloc[0]
    assert row["name"] == "Spaced Out"
    assert row["url"] == "https://example.com/x"
    assert row["availability"] == "In Stock"  # canonical label
    assert row["source_product_id"] == "x_1"


def test_price_string_parsing_and_currency():
    df = records_to_dataframe(
        [{"name": "A", "url": "https://example.com/a", "price": "£1,052.15"}]
    )
    result = clean_products(df)
    row = result.frame.iloc[0]
    assert float(row["price"]) == 1052.15
    assert row["currency"] == "GBP"
    assert row["raw_price"] == "£1,052.15"  # original preserved


def test_invalid_price_becomes_na():
    df = records_to_dataframe(
        [{"name": "A", "url": "https://example.com/a", "price": "not-a-price"}]
    )
    result = clean_products(df)
    assert result.frame.iloc[0]["price"] is pd.NA
    assert result.invalid_prices == 1


def test_rating_out_of_range_dropped():
    df = records_to_dataframe(
        [{"name": "A", "url": "https://example.com/a", "rating": 9},
         {"name": "B", "url": "https://example.com/b", "rating": 4}]
    )
    result = clean_products(df)
    assert result.frame.iloc[0]["rating"] is pd.NA
    assert float(result.frame.iloc[1]["rating"]) == 4.0
    assert result.invalid_ratings == 1


def test_duplicates_removed(sample_records):
    df = records_to_dataframe(sample_records)  # contains a duplicate URL
    result = clean_products(df)
    assert result.duplicates_removed == 1
    assert len(result.frame) == 3
    assert result.frame["url"].is_unique


def test_url_fragment_stripped():
    df = records_to_dataframe(
        [{"name": "A", "url": "https://example.com/a#reviews"}]
    )
    result = clean_products(df)
    assert result.frame.iloc[0]["url"] == "https://example.com/a"


def test_scraped_at_parsed_to_datetime(sample_records):
    result = clean_products(records_to_dataframe(sample_records))
    assert pd.api.types.is_datetime64_any_dtype(result.frame["scraped_at"])


def test_empty_dataframe():
    result = clean_products(pd.DataFrame())
    assert isinstance(result, CleanResult)
    assert result.frame.empty
    assert result.rows_in == 0


def test_malformed_input_missing_columns():
    df = pd.DataFrame([{"title": "Only a title", "cost": "£3"}])
    result = clean_products(df)
    # required-field rows are dropped; frame keeps the canonical columns
    assert "name" in result.frame.columns and "url" in result.frame.columns
    assert result.frame.empty


def test_availability_normalisation_counts():
    df = records_to_dataframe(
        [{"name": "A", "url": "https://example.com/a", "availability": "In stock"},
         {"name": "B", "url": "https://example.com/b", "availability": "Out of stock"}]
    )
    result = clean_products(df)
    # both raw labels ("In stock"/"Out of stock") were mapped to canonical ones
    assert result.normalised_availability == 2
    assert set(result.frame["availability"]) == {"In Stock", "Out of Stock"}


def test_derived_columns(sample_records):
    result = clean_products(records_to_dataframe(sample_records))
    enriched = add_derived_columns(result.frame)
    assert "price_bucket" in enriched.columns
    assert "availability_status" in enriched.columns
    assert "rating_band" in enriched.columns
    assert enriched["availability_status"].iloc[0] == "Available"


def test_derived_columns_empty_df():
    out = add_derived_columns(pd.DataFrame(columns=["name", "url"]))
    assert out.empty
    assert "availability_status" not in out.columns
