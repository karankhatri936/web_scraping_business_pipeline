"""Shared data models for the extracted product record contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Canonical record fields produced by the scraper and consumed by every
# later pipeline stage. Only fields the target site actually exposes are
# listed here; optional fields default to None when the site has no value.
RECORD_FIELDS = (
    "name",
    "url",
    "price",
    "currency",
    "category",
    "availability",
    "rating",
    "image_url",
    "source_product_id",
    "scraped_at",
)


def utc_now_iso() -> str:
    """Current UTC timestamp as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProductRecord:
    """A single scraped product in the pipeline-wide record contract."""

    name: str
    url: str
    price: float | None = None
    currency: str | None = None
    category: str | None = None
    availability: str | None = None
    rating: float | None = None
    image_url: str | None = None
    source_product_id: str | None = None
    scraped_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in RECORD_FIELDS}
