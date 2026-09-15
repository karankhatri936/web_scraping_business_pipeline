"""Database schema definitions.

Three tables support the competitor-monitoring use case:

* ``products``       - current catalogue snapshot (one row per product, upserted)
* ``price_history``  - append-only price observations per run
* ``scrape_runs``    - run bookkeeping (when, how many records, status)
"""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_product_id TEXT UNIQUE,
    name              TEXT NOT NULL,
    url               TEXT NOT NULL UNIQUE,
    price             REAL,
    currency          TEXT,
    category          TEXT,
    availability      TEXT,
    rating            REAL,
    image_url         TEXT,
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_source_id ON products(source_product_id);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL DEFAULT 'running',
    categories     INTEGER NOT NULL DEFAULT 0,
    pages_visited  INTEGER NOT NULL DEFAULT 0,
    pages_failed   INTEGER NOT NULL DEFAULT 0,
    records_found  INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS price_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    source_product_id TEXT,
    name              TEXT NOT NULL,
    url               TEXT NOT NULL,
    price             REAL,
    currency          TEXT,
    captured_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(source_product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_run ON price_history(run_id);
"""
