"""CSV report generation.

Writes the cleaned dataset (plus derived columns) to a timestamped CSV file
using UTF-8 with BOM so Excel opens it correctly on Windows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from utils.exceptions import ReportGenerationError
from utils.logger import get_logger

logger = get_logger(__name__)

CSV_COLUMNS = [
    "name",
    "url",
    "price",
    "currency",
    "category",
    "availability",
    "availability_status",
    "rating",
    "rating_band",
    "price_bucket",
    "image_url",
    "source_product_id",
    "scraped_at",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def write_products_csv(
    df: pd.DataFrame, output_dir: Path | str, filename: str | None = None
) -> Path:
    """Write the cleaned dataset to CSV; returns the written path.

    Columns not present in *df* are skipped; extra columns are appended so
    the report never hides data the pipeline produced.
    """
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / (filename or f"products_{_timestamp()}.csv")
        if df.empty:
            out = pd.DataFrame(columns=CSV_COLUMNS)
        else:
            ordered = [c for c in CSV_COLUMNS if c in df.columns]
            extra = [c for c in df.columns if c not in ordered]
            out = df[ordered + extra]
        out.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("CSV report written: %s (%d row(s))", path, len(out))
        return path
    except OSError as exc:
        raise ReportGenerationError(f"Could not write CSV report: {exc}") from exc
