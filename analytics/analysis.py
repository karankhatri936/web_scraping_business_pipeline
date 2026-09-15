"""Business analytics over the cleaned product dataset.

Produces KPIs and small aggregate tables that feed the Excel report. Only
fields actually present in the scraped data are used - no sales, revenue or
market-share figures are invented.

All functions are empty-dataset safe so scheduled runs can analyse a cold or
failed run without crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from data.transformer import PRICE_BIN_EDGES, PRICE_BIN_LABELS
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AnalysisResult:
    """Bundle of KPIs and aggregate tables for reporting."""

    has_data: bool = False
    kpis: dict[str, Any] = field(default_factory=dict)
    by_category: pd.DataFrame = field(default_factory=pd.DataFrame)
    availability: pd.DataFrame = field(default_factory=pd.DataFrame)
    rating_distribution: pd.DataFrame = field(default_factory=pd.DataFrame)
    price_distribution: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_rated: pd.DataFrame = field(default_factory=pd.DataFrame)
    cheapest: pd.DataFrame = field(default_factory=pd.DataFrame)
    price_changes: pd.DataFrame = field(default_factory=pd.DataFrame)


def _first_currency(df: pd.DataFrame) -> str | None:
    if "currency" not in df.columns:
        return None
    modes = df["currency"].dropna()
    return str(modes.mode().iloc[0]) if not modes.empty else None


def compute_kpis(df: pd.DataFrame) -> dict[str, Any]:
    """Headline KPIs for the dashboard sheet."""
    kpis: dict[str, Any] = {
        "total_products": int(len(df)),
        "unique_products": int(df["url"].nunique()) if "url" in df.columns else 0,
        "categories": int(df["category"].nunique()) if "category" in df.columns else 0,
        "currency": _first_currency(df),
    }

    if "price" in df.columns and df["price"].notna().any():
        prices = df["price"].astype(float)
        kpis.update(
            {
                "avg_price": round(float(prices.mean()), 2),
                "median_price": round(float(prices.median()), 2),
                "min_price": round(float(prices.min()), 2),
                "max_price": round(float(prices.max()), 2),
            }
        )
    else:
        kpis.update(
            {"avg_price": None, "median_price": None, "min_price": None, "max_price": None}
        )

    if "rating" in df.columns and df["rating"].notna().any():
        kpis["avg_rating"] = round(float(df["rating"].astype(float).mean()), 2)
    else:
        kpis["avg_rating"] = None

    if "availability_status" in df.columns:
        counts = df["availability_status"].value_counts()
        kpis["in_stock"] = int(counts.get("Available", 0))
        kpis["out_of_stock"] = int(counts.get("Unavailable", 0))
    else:
        kpis["in_stock"] = 0
        kpis["out_of_stock"] = 0

    if "price" in df.columns and df["price"].notna().any():
        kpis["price_span"] = round(
            float(df["price"].astype(float).max() - df["price"].astype(float).min()), 2
        )
    else:
        kpis["price_span"] = None
    return kpis


def compute_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Per-category aggregates (counts, price stats, ratings)."""
    if df.empty or "category" not in df.columns:
        return pd.DataFrame(
            columns=[
                "category", "product_count", "in_stock", "avg_price",
                "min_price", "max_price", "avg_rating",
            ]
        )
    grouped = df.groupby("category", dropna=False)
    rows = []
    for category, sub in grouped:
        row: dict[str, Any] = {
            "category": category,
            "product_count": int(len(sub)),
            "in_stock": (
                int((sub["availability_status"] == "Available").sum())
                if "availability_status" in sub.columns
                else 0
            ),
        }
        if "price" in sub.columns and sub["price"].notna().any():
            prices = sub["price"].astype(float)
            row.update(
                {
                    "avg_price": round(float(prices.mean()), 2),
                    "min_price": round(float(prices.min()), 2),
                    "max_price": round(float(prices.max()), 2),
                }
            )
        else:
            row.update({"avg_price": None, "min_price": None, "max_price": None})
        row["avg_rating"] = (
            round(float(sub["rating"].astype(float).mean()), 2)
            if "rating" in sub.columns and sub["rating"].notna().any()
            else None
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        "product_count", ascending=False
    ).reset_index(drop=True)


def compute_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Availability breakdown (uses derived status when present)."""
    column = (
        "availability_status"
        if "availability_status" in df.columns
        else ("availability" if "availability" in df.columns else None)
    )
    if column is None or df.empty:
        return pd.DataFrame(columns=["availability", "product_count"])
    counts = df[column].value_counts(dropna=False).reset_index()
    counts.columns = ["availability", "product_count"]
    counts["availability"] = counts["availability"].fillna("Unknown")
    return counts


def compute_rating_distribution(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "rating" not in df.columns or df["rating"].notna().sum() == 0:
        return pd.DataFrame(columns=["rating", "product_count"])
    counts = (
        df["rating"].astype(float).round().value_counts().sort_index().reset_index()
    )
    counts.columns = ["rating", "product_count"]
    counts["rating"] = counts["rating"].astype(int).astype(str) + " star"
    return counts


def compute_price_distribution(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "price" not in df.columns or df["price"].notna().sum() == 0:
        return pd.DataFrame(columns=["price_bucket", "product_count"])
    buckets = pd.cut(
        df["price"].astype(float), bins=PRICE_BIN_EDGES, labels=PRICE_BIN_LABELS,
        right=False,
    )
    counts = buckets.value_counts().reindex(PRICE_BIN_LABELS, fill_value=0)
    out = counts.reset_index()
    out.columns = ["price_bucket", "product_count"]
    out["price_bucket"] = out["price_bucket"].astype(str)
    return out


def compute_top_rated(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    if df.empty or "rating" not in df.columns:
        return pd.DataFrame(columns=["name", "category", "rating", "price", "url"])
    subset = df[df["rating"].notna()].copy()
    subset = subset.sort_values(
        ["rating", "price"], ascending=[False, True], na_position="last"
    ).head(top_n)
    return subset[["name", "category", "rating", "price", "url"]].reset_index(drop=True)


def compute_cheapest(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    if df.empty or "price" not in df.columns:
        return pd.DataFrame(columns=["name", "category", "price", "rating", "url"])
    subset = df[df["price"].notna()].copy()
    subset = subset.sort_values("price", ascending=True).head(top_n)
    return subset[["name", "category", "price", "rating", "url"]].reset_index(drop=True)


def compute_price_changes(
    df: pd.DataFrame, previous_prices: pd.DataFrame | None
) -> pd.DataFrame:
    """Compare current prices with the previous run (monitoring KPI)."""
    columns = ["name", "category", "previous_price", "current_price", "change"]
    if previous_prices is None or previous_prices.empty or df.empty:
        return pd.DataFrame(columns=columns)
    if "url" not in df.columns or "url" not in previous_prices.columns:
        return pd.DataFrame(columns=columns)
    current = df[df["price"].notna()][["name", "category", "url", "price"]]
    merged = current.merge(previous_prices[["url", "previous_price"]], on="url")
    if merged.empty:
        return pd.DataFrame(columns=columns)
    merged["change"] = (
        merged["price"].astype(float) - merged["previous_price"].astype(float)
    ).round(2)
    merged = merged.rename(columns={"price": "current_price"})
    return merged[columns].reset_index(drop=True)


def compute_analysis(
    products: pd.DataFrame,
    previous_prices: pd.DataFrame | None = None,
    top_n: int = 10,
) -> AnalysisResult:
    """Run the full analysis bundle over the cleaned dataset."""
    df = products if products is not None else pd.DataFrame()
    result = AnalysisResult(has_data=not df.empty)
    if df.empty:
        logger.info("Analysis skipped: dataset is empty")
        return result
    result.kpis = compute_kpis(df)
    result.by_category = compute_by_category(df)
    result.availability = compute_availability(df)
    result.rating_distribution = compute_rating_distribution(df)
    result.price_distribution = compute_price_distribution(df)
    result.top_rated = compute_top_rated(df, top_n)
    result.cheapest = compute_cheapest(df, top_n)
    result.price_changes = compute_price_changes(df, previous_prices)
    logger.info(
        "Analysis computed: %d product(s), %d category(ies)",
        result.kpis.get("total_products", 0),
        result.kpis.get("categories", 0),
    )
    return result

