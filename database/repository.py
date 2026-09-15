"""Data-access layer for the pipeline database.

All queries are parameterised. The repository is the ONLY module that talks
SQL; scraping, cleaning, analytics and reports never see the database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data.models import utc_now_iso
from database.connection import DatabaseConnection
from database.models import SCHEMA_SQL
from utils.exceptions import DatabaseError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RunRecord:
    """Bookkeeping entry for one pipeline run."""

    id: int
    started_at: str
    status: str


class ProductRepository:
    """CRUD + monitoring queries over the SQLite database."""

    def __init__(self, db_path: Path | str) -> None:
        self.db = DatabaseConnection(db_path)

    # -- schema -------------------------------------------------------------
    def init_db(self) -> None:
        """Create tables when missing (idempotent)."""
        with self.db.session() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("Database initialised at %s", self.db.db_path)

    # -- run bookkeeping ------------------------------------------------------
    def start_run(self) -> int:
        """Register a new run row and return its id."""
        with self.db.session() as conn:
            cursor = conn.execute(
                "INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
                (utc_now_iso(),),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict[str, int]) -> None:
        """Store final counters for a run."""
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE scrape_runs
                SET finished_at = ?, status = ?, categories = ?, pages_visited = ?,
                    pages_failed = ?, records_found = ?, records_accepted = ?,
                    records_rejected = ?
                WHERE id = ?
                """,
                (
                    utc_now_iso(),
                    status,
                    stats.get("categories", 0),
                    stats.get("pages_visited", 0),
                    stats.get("pages_failed", 0),
                    stats.get("records_found", 0),
                    stats.get("records_accepted", 0),
                    stats.get("records_rejected", 0),
                    run_id,
                ),
            )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT id, started_at, status FROM scrape_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return RunRecord(row["id"], row["started_at"], row["status"]) if row else None


    # -- product upserts ------------------------------------------------------
    def upsert_products(self, df: pd.DataFrame, run_id: int) -> int:
        """Upsert the cleaned product snapshot + append price history.

        Deduplication and update behaviour:
        * ``url`` is the natural key; a repeated URL updates price/availability
          etc. and refreshes ``last_seen_at``.
        * new products get ``first_seen_at`` = now.
        Returns the number of rows written (upserted).
        """
        now = utc_now_iso()
        written = 0
        with self.db.transaction() as conn:
            for row in df.to_dict(orient="records"):
                written += self._upsert_product(conn, row, now)
                self._insert_price_history(conn, row, run_id, now)
        logger.info("Upserted %d product row(s)", written)
        return written

    @staticmethod
    def _upsert_product(conn: sqlite3.Connection, row: dict[str, Any], now: str) -> int:
        price = row.get("price")
        price = float(price) if price is not None and pd.notna(price) else None
        rating = row.get("rating")
        rating = float(rating) if rating is not None and pd.notna(rating) else None
        cursor = conn.execute(
            """
            INSERT INTO products (
                source_product_id, name, url, price, currency, category,
                availability, rating, image_url, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                source_product_id = excluded.source_product_id,
                name              = excluded.name,
                price             = excluded.price,
                currency          = excluded.currency,
                category          = excluded.category,
                availability      = excluded.availability,
                rating            = excluded.rating,
                image_url         = excluded.image_url,
                last_seen_at      = excluded.last_seen_at
            """,
            (
                row.get("source_product_id"),
                row["name"],
                row["url"],
                price,
                row.get("currency"),
                row.get("category"),
                row.get("availability"),
                rating,
                row.get("image_url"),
                now,
                now,
            ),
        )
        return cursor.rowcount if cursor.rowcount > 0 else 1

    @staticmethod
    def _insert_price_history(
        conn: sqlite3.Connection, row: dict[str, Any], run_id: int, now: str
    ) -> None:
        price = row.get("price")
        price = float(price) if price is not None and pd.notna(price) else None
        conn.execute(
            """
            INSERT INTO price_history (
                run_id, source_product_id, name, url, price, currency, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row.get("source_product_id"),
                row["name"],
                row["url"],
                price,
                row.get("currency"),
                now,
            ),
        )

    # -- queries ---------------------------------------------------------------
    def get_products(self) -> pd.DataFrame:
        """Current product snapshot as a DataFrame (empty when db is empty)."""
        with self.db.session() as conn:
            return pd.read_sql_query(
                """
                SELECT source_product_id, name, url, price, currency, category,
                       availability, rating, image_url, first_seen_at, last_seen_at
                FROM products ORDER BY category, name
                """,
                conn,
            )

    def get_previous_prices(self, run_id: int) -> pd.DataFrame:
        """Latest pre-run price per product from price_history.

        Used to compute price movements between scheduled runs.
        """
        with self.db.session() as conn:
            return pd.read_sql_query(
                """
                SELECT ph.source_product_id, ph.url, ph.price AS previous_price
                FROM price_history ph
                WHERE ph.run_id < ?
                  AND ph.price IS NOT NULL
                  AND ph.id = (
                      SELECT MAX(ph2.id) FROM price_history ph2
                      WHERE ph2.url = ph.url AND ph2.run_id < ?
                        AND ph2.price IS NOT NULL
                  )
                """,
                conn,
                params=(run_id, run_id),
            )

    def count_products(self) -> int:
        with self.db.session() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()
        return int(row["n"])

    def get_runs(self) -> pd.DataFrame:
        with self.db.session() as conn:
            return pd.read_sql_query(
                "SELECT * FROM scrape_runs ORDER BY id", conn
            )
