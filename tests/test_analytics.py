"""Tests for the business analytics layer."""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.analysis import compute_analysis, compute_kpis


@pytest.fixture
def products_df():
    return pd.DataFrame(
        [
            {"name": "A", "url": "u1", "price": 10.0, "category": "Travel",
             "availability_status": "Available", "rating": 5},
            {"name": "B", "url": "u2", "price": 30.0, "category": "Travel",
             "availability_status": "Available", "rating": 3},
            {"name": "C", "url": "u3", "price": 55.0, "category": "Mystery",
             "availability_status": "Unavailable", "rating": 4},
            {"name": "D", "url": "u4", "price": None, "category": "Mystery",
             "availability_status": "Unknown", "rating": None},
        ]
    )


def test_kpis_normal_dataset(products_df):
    kpis = compute_kpis(products_df)
    assert kpis["total_products"] == 4
    assert kpis["unique_products"] == 4
    assert kpis["categories"] == 2
    assert kpis["in_stock"] == 2
    assert kpis["out_of_stock"] == 1
    assert kpis["avg_price"] == 31.67  # (10+30+55)/3, two decimals
    assert kpis["min_price"] == 10.0
    assert kpis["max_price"] == 55.0
    assert kpis["price_span"] == 45.0
    assert kpis["avg_rating"] == 4.0


def test_kpis_empty_dataset():
    kpis = compute_kpis(pd.DataFrame())
    assert kpis["total_products"] == 0
    assert kpis["avg_price"] is None
    assert kpis["avg_rating"] is None


def test_kpis_missing_optional_columns():
    df = pd.DataFrame([{"name": "A", "url": "u1"}])
    kpis = compute_kpis(df)
    assert kpis["total_products"] == 1
    assert kpis["avg_price"] is None
    assert kpis["avg_rating"] is None
    assert kpis["in_stock"] == 0


def test_analysis_by_category(products_df):
    result = compute_analysis(products_df)
    by_cat = result.by_category.set_index("category")
    assert int(by_cat.loc["Travel", "product_count"]) == 2
    assert float(by_cat.loc["Travel", "avg_price"]) == 20.0
    assert int(by_cat.loc["Mystery", "product_count"]) == 2
    # sorted by product_count desc; tie order between the two is unspecified
    assert sorted(by_cat.index.tolist()) == ["Mystery", "Travel"]
    assert by_cat["product_count"].tolist() == [2, 2]


def test_analysis_availability_and_distributions(products_df):
    result = compute_analysis(products_df)
    avail = result.availability.set_index("availability")["product_count"].to_dict()
    assert avail == {"Available": 2, "Unavailable": 1, "Unknown": 1}
    ratings = result.rating_distribution.set_index("rating")["product_count"].to_dict()
    assert ratings == {"3 star": 1, "4 star": 1, "5 star": 1}
    buckets = result.price_distribution.set_index("price_bucket")["product_count"].to_dict()
    # labels are currency-neutral; 10.0 falls in [10,20) because bins are
    # half-open [start, end)
    assert buckets["10-20"] == 1
    assert buckets["30-40"] == 1
    assert buckets["50+"] == 1


def test_analysis_rankings(products_df):
    result = compute_analysis(products_df, top_n=2)
    assert result.top_rated.iloc[0]["name"] == "A"  # rating 5 first
    assert len(result.top_rated) == 2
    assert result.cheapest.iloc[0]["name"] == "A"  # 10.0 is cheapest
    assert len(result.cheapest) == 2


def test_analysis_price_changes(products_df):
    previous = pd.DataFrame(
        [{"url": "u1", "previous_price": 12.0}, {"url": "u3", "previous_price": 50.0}]
    )
    result = compute_analysis(products_df, previous_prices=previous)
    changes = result.price_changes.set_index("name")["change"].to_dict()
    assert changes["A"] == -2.0
    assert changes["C"] == 5.0


def test_analysis_no_previous_data(products_df):
    result = compute_analysis(products_df, previous_prices=None)
    assert result.price_changes.empty


def test_analysis_empty_dataset():
    result = compute_analysis(pd.DataFrame())
    assert result.has_data is False
    assert result.by_category.empty
    assert result.kpis == {}


def test_analysis_duplicate_rows_counted(products_df):
    duplicated = pd.concat([products_df, products_df.iloc[[0]]], ignore_index=True)
    kpis = compute_kpis(duplicated)
    assert kpis["total_products"] == 5
    assert kpis["unique_products"] == 4
