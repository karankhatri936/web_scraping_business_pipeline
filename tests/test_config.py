"""Tests for configuration loading and logging setup."""

from __future__ import annotations

import logging

import pytest

import config
from config import load_settings


def test_defaults_without_env(monkeypatch):
    for name in (
        "TARGET_BASE_URL", "BROWSER_HEADLESS", "NAVIGATION_TIMEOUT_SECONDS",
        "REQUEST_DELAY_SECONDS", "MAX_PAGES_PER_CATEGORY", "MAX_CATEGORIES",
        "MAX_PRODUCTS", "DB_PATH", "OUTPUT_CSV_DIR", "OUTPUT_EXCEL_DIR",
        "LOG_DIR", "LOG_LEVEL", "REPORT_TOP_N", "SCHEDULE_INTERVAL_MINUTES",
        "SCHEDULE_MAX_RUNS", "PAGE_LOAD_RETRIES", "RESPECT_ROBOTS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(tmp_env_missing(monkeypatch))
    assert settings.base_url == "https://books.toscrape.com/"
    assert settings.scraper.headless is True
    assert settings.scraper.request_delay_seconds == 1.0
    assert settings.output.db_path == config.PROJECT_ROOT / "data" / "products.db"


def tmp_env_missing(monkeypatch):
    """Return a non-existent env path so no developer .env leaks into tests."""
    return config.PROJECT_ROOT / "tests" / "_no_such_env_file.env"


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("TARGET_BASE_URL", "https://example.com/")
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("MAX_PAGES_PER_CATEGORY", "7")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("LOG_LEVEL", "debug")
    settings = load_settings(tmp_env_missing(monkeypatch))
    assert settings.base_url == "https://example.com/"
    assert settings.scraper.request_delay_seconds == 0.25
    assert settings.scraper.max_pages_per_category == 7
    assert settings.output.db_path == tmp_path / "custom.db"
    assert settings.output.log_level == "DEBUG"


def test_invalid_number_raises(monkeypatch):
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="not a valid number"):
        load_settings(tmp_env_missing(monkeypatch))


def test_empty_base_url_raises(monkeypatch):
    monkeypatch.setenv("TARGET_BASE_URL", "   ")
    with pytest.raises(ValueError, match="empty"):
        load_settings(tmp_env_missing(monkeypatch))


def test_output_directories_created(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OUTPUT_CSV_DIR", str(tmp_path / "csv"))
    monkeypatch.setenv("OUTPUT_EXCEL_DIR", str(tmp_path / "excel"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sub" / "db.sqlite3"))
    settings = load_settings(tmp_env_missing(monkeypatch))
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "csv").is_dir()
    assert (tmp_path / "excel").is_dir()
    assert (tmp_path / "sub").is_dir()


def test_configure_logging_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    settings = load_settings(tmp_env_missing(monkeypatch))
    config.configure_logging(settings)
    logging.getLogger("pipeline.test").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_file = tmp_path / "logs" / "pipeline.log"
    assert log_file.exists()
    assert "hello from the test" in log_file.read_text(encoding="utf-8")
