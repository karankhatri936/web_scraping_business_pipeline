"""Tests for the SQLite storage layer (temporary databases)."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data.cleaner import clean_products, records_to_dataframe
from data.models import ProductRecord
from database.connection import DatabaseConnection
from database.repository import ProductRepository
from utils.exceptions import DatabaseError


@pytest.fixture
def repo(tmp_path) -> ProductRepository:
    repository = ProductRepository(tmp_path / "test.db")
    repository.init_db()
    return repository


@pytest.fixture
def cleaned_df(sample_records):
    accepted = [r for r in sample_records]
    return clean_products(records_to_dataframe(accepted)).frame


def test_init_db_creates_tables(tmp_path):
    repo = ProductRepository(tmp_path / "fresh.db")
    repo.init_db()
    with DatabaseConnection(tmp_path / "fresh.db").session() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"products", "price_history", "scrape_runs"} <= tables


def test_init_db_idempotent(tmp_path):
    repo = ProductRepository(tmp_path / "fresh.db")
    repo.init_db()
    repo.init_db()  # no error


def test_insert_and_retrieve(repo, cleaned_df):
    run_id = repo.start_run()
    written = repo.upsert_products(cleaned_df, run_id)
    assert written == len(cleaned_df)
    stored = repo.get_products()
    assert len(stored) == len(cleaned_df)
    assert set(stored["name"]) == set(cleaned_df["name"])
    assert repo.count_products() == len(cleaned_df)


def test_upsert_updates_existing_product(repo, cleaned_df):
    run_id = repo.start_run()
    repo.upsert_products(cleaned_df, run_id)

    run2 = repo.start_run()  # price history FK needs a real run row
    changed = cleaned_df.copy()
    changed.loc[changed["name"] == "Tipping the Velvet", "price"] = 39.99
    repo.upsert_products(changed, run2)

    stored = repo.get_products()
    assert repo.count_products() == len(cleaned_df)  # no duplicate rows
    row = stored[stored["name"] == "Tipping the Velvet"].iloc[0]
    assert float(row["price"]) == 39.99


def test_price_history_appended_per_run(repo, cleaned_df):
    run1 = repo.start_run()
    repo.upsert_products(cleaned_df, run1)
    run2 = repo.start_run()
    repo.upsert_products(cleaned_df, run2)

    with DatabaseConnection(repo.db.db_path).session() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM price_history").fetchone()["n"]
    assert count == 2 * len(cleaned_df)
    # previous prices only exist for products that actually had a price
    previous = repo.get_previous_prices(run2)
    assert len(previous) == 2  # 3 products, one without a price


def test_previous_prices_excludes_current_run(repo, cleaned_df):
    run1 = repo.start_run()
    repo.upsert_products(cleaned_df, run1)
    assert repo.get_previous_prices(run1).empty


def test_run_bookkeeping(repo, cleaned_df):
    run_id = repo.start_run()
    run = repo.get_run(run_id)
    assert run is not None and run.status == "running"
    repo.finish_run(
        run_id, "success",
        {"records_found": 10, "records_accepted": 9, "records_rejected": 1},
    )
    run = repo.get_run(run_id)
    assert run.status == "success"
    runs = repo.get_runs()
    assert runs.iloc[0]["records_accepted"] == 9


def test_empty_database_returns_empty_frame(repo):
    stored = repo.get_products()
    assert isinstance(stored, pd.DataFrame)
    assert stored.empty
    assert repo.count_products() == 0


def test_invalid_record_rejected_by_db_constraint(repo, cleaned_df):
    run_id = repo.start_run()
    broken = pd.concat(
        [cleaned_df, pd.DataFrame([{"name": None, "url": None}])],
        ignore_index=True,
    )
    with pytest.raises(DatabaseError):
        repo.upsert_products(broken, run_id)
    # rollback leaves the table untouched
    assert repo.count_products() == 0


def test_session_rollback_on_error(tmp_path):
    repo = ProductRepository(tmp_path / "fresh.db")
    repo.init_db()
    with pytest.raises(DatabaseError), DatabaseConnection(tmp_path / "fresh.db").session() as conn:
        conn.execute(
            "INSERT INTO scrape_runs (started_at, status) VALUES ('t', 'running')"
        )
        raise sqlite3.OperationalError("boom")
    with DatabaseConnection(tmp_path / "fresh.db").session() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM scrape_runs").fetchone()["n"]
    assert count == 0


def test_product_record_to_dict_roundtrip():
    record = ProductRecord(name="X", url="https://example.com/x")
    data = record.to_dict()
    assert data["name"] == "X"
    assert data["price"] is None
