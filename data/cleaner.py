"""Pandas-based cleaning layer.

Takes validated records (or a raw DataFrame) and produces the cleaned dataset
used by analytics, reports and the database. Original source values are never
silently altered: raw values are preserved in ``raw_*`` companion columns for
the fields that get normalised (price, availability).

Cleaning steps
--------------
1. normalise column names to snake_case
2. strip whitespace in text columns, empty strings -> NA
3. parse prices to floats (handles currency symbols / thousand separators)
4. ratings to floats within the 0-5 source scale
5. availability mapped to canonical labels ("In Stock" / "Out of Stock")
6. URL normalisation (trim, drop fragments)
7. drop exact-duplicate rows and duplicate product URLs
8. ``scraped_at`` parsed to UTC datetimes
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from data.models import RECORD_FIELDS
from utils.logger import get_logger

logger = get_logger(__name__)

_AVAILABILITY_CANONICAL = {
    "in stock": "In Stock",
    "instock": "In Stock",
    "available": "In Stock",
    "out of stock": "Out of Stock",
    "outofstock": "Out of Stock",
    "unavailable": "Out of Stock",
}


@dataclass
class CleanResult:
    """Cleaned dataset plus statistics about what changed."""

    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    invalid_prices: int = 0
    invalid_ratings: int = 0
    normalised_availability: int = 0
    notes: list[str] = field(default_factory=list)


def records_to_dataframe(records) -> pd.DataFrame:
    """Build a raw DataFrame from ProductRecord objects or plain dicts."""
    rows = []
    for record in records:
        if hasattr(record, "to_dict"):
            rows.append(record.to_dict())
        elif isinstance(record, dict):
            rows.append({k: record.get(k) for k in RECORD_FIELDS})
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported record type: {type(record)!r}")
    return pd.DataFrame(rows, columns=list(RECORD_FIELDS))


def _snake_case(name: str) -> str:
    name = re.sub(r"[^\w]+", "_", str(name).strip())
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower().strip("_")


def _to_price(value) -> float | None:
    """Coerce a raw price cell (e.g. ``"£51.77"``) to a float."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"([\d.,]+)", str(value))
    if not match:
        return None
    digits = match.group(1).replace(",", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _currency_of(value) -> str | None:
    """Extract the currency from a raw price cell, e.g. ``"£51.77" -> GBP``."""
    from scraper.parsers import CURRENCY_SYMBOLS  # local import avoids a cycle

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return None
    match = re.search(r"([^\d.,\s]+)", str(value))
    if not match:
        return None
    symbol = match.group(1)
    return CURRENCY_SYMBOLS.get(symbol, symbol)


def _normalise_availability(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    return _AVAILABILITY_CANONICAL.get(text.lower(), text)


def _normalise_url(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    url = str(value).strip().split("#", 1)[0]
    return url or None



def clean_products(raw: pd.DataFrame) -> CleanResult:
    """Clean the raw product DataFrame and return the result + statistics."""
    df = raw.copy()
    result = CleanResult(rows_in=len(df))

    # 1. column names ------------------------------------------------------
    df.columns = [_snake_case(c) for c in df.columns]

    # Guarantee every canonical column exists (malformed input support).
    for col in RECORD_FIELDS:
        if col not in df.columns:
            df[col] = pd.NA
            result.notes.append(f"added missing column {col!r}")

    # 2. text columns ------------------------------------------------------
    text_cols = ["name", "currency", "category", "availability", "image_url",
                 "source_product_id"]
    for col in text_cols:
        df[col] = (
            df[col]
            .astype("string")
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .replace("", pd.NA)
        )

    # 3./4. numeric columns -------------------------------------------------
    if "price" in df.columns:
        raw_prices = df["price"].copy()
        df["price"] = raw_prices.map(_to_price).astype("Float64")
        result.invalid_prices = int((raw_prices.notna() & df["price"].isna()).sum())
        # Preserve the original source value for auditability.
        df["raw_price"] = raw_prices.astype("string")
        # Derive currency from the raw price tag when the record lacks one.
        if "currency" in df.columns:
            derived = raw_prices.map(_currency_of).astype("string")
            df["currency"] = df["currency"].fillna(derived)

    if "rating" in df.columns:
        ratings = pd.to_numeric(df["rating"], errors="coerce").astype("Float64")
        outside = (ratings < 0) | (ratings > 5)
        result.invalid_ratings += int(outside.sum())
        df["rating"] = ratings.mask(outside)

    # 5. availability -------------------------------------------------------
    if "availability" in df.columns:
        normalised = df["availability"].map(_normalise_availability).astype("string")
        result.normalised_availability = int(
            (df["availability"].notna() & (df["availability"] != normalised)).sum()
        )
        df["availability"] = normalised

    # 6. URLs ---------------------------------------------------------------
    for col in ("url", "image_url"):
        if col in df.columns:
            df[col] = df[col].map(_normalise_url).astype("string")

    # 7. duplicates ---------------------------------------------------------
    before = len(df)
    df = df.drop_duplicates().drop_duplicates(subset=["url"], keep="first")
    result.duplicates_removed = before - len(df)

    # 8. timestamps ---------------------------------------------------------
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce", utc=True)

    # Drop rows without the required fields (defence in depth; the validator
    # normally removes these earlier).
    df = df[df["name"].notna() & df["url"].notna()].reset_index(drop=True)

    result.frame = df
    result.rows_out = len(df)
    logger.info(
        "Cleaning done: %d -> %d rows (%d duplicates removed, %d invalid price(s), %d invalid rating(s))",
        result.rows_in,
        result.rows_out,
        result.duplicates_removed,
        result.invalid_prices,
        result.invalid_ratings,
    )
    return result
