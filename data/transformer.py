"""Derived-field transformations.

Adds analytically useful columns to the cleaned dataset without altering any
source values:

* ``price_bucket``    - banded price label (0-10, 10-20, ...) when prices exist
* ``availability_status`` - collapsed to Available / Unavailable / Unknown
* ``rating_band``     - Low (1-2) / Medium (3) / High (4-5) when ratings exist

Everything is derived only from fields the source site actually provides.
Bucket labels are deliberately currency-neutral: the currency of a price is
carried in the ``currency`` column, so the label must not assume one.
"""

from __future__ import annotations

import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

# Single source of truth for the price banding used by both the derived column
# and the analytics price distribution (imported by ``analytics.analysis``).
PRICE_BIN_EDGES = [0, 10, 20, 30, 40, 50, float("inf")]
PRICE_BIN_LABELS = ["0-10", "10-20", "20-30", "30-40", "40-50", "50+"]


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with derived analysis columns appended."""
    out = df.copy()

    if "price" in out.columns and out["price"].notna().any():
        buckets = pd.cut(
            out["price"].astype("float"),
            bins=PRICE_BIN_EDGES,
            labels=PRICE_BIN_LABELS,
            right=False,
        )
        out["price_bucket"] = buckets.astype("string")

    if "availability" in out.columns:
        def status(value: object) -> str:
            text = str(value) if value is not None and pd.notna(value) else ""
            lowered = text.lower()
            if "in stock" in lowered or "instock" in lowered:
                return "Available"
            if "out of stock" in lowered or "outofstock" in lowered:
                return "Unavailable"
            return "Unknown"

        out["availability_status"] = out["availability"].map(status).astype("string")

    if "rating" in out.columns and out["rating"].notna().any():
        def band(value: object) -> str | None:
            if value is None or pd.isna(value):
                return None
            value = float(value)
            if value < 3:
                return "Low (1-2)"
            if value < 4:
                return "Medium (3)"
            return "High (4-5)"

        out["rating_band"] = out["rating"].map(band).astype("string")

    logger.info("Derived columns added: %s", [c for c in out.columns if c not in df.columns])
    return out
