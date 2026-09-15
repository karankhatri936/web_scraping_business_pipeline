"""Application configuration.

All tunable settings live here (or in the optional ``.env`` file) instead of
being scattered across the codebase. Paths are resolved relative to the
project root so the pipeline behaves the same regardless of the current
working directory.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid number") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid integer") from exc


def _resolve(value: str | Path) -> Path:
    """Resolve *value* against the project root when it is relative."""
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass(frozen=True)
class ScraperSettings:
    """Settings for the browser and the scraping run."""

    base_url: str
    headless: bool = True
    navigation_timeout_seconds: float = 30.0
    request_delay_seconds: float = 1.0
    page_load_retries: int = 1
    max_pages_per_category: int = 0  # 0 = unlimited
    max_categories: int = 0          # 0 = unlimited
    max_products: int = 0            # 0 = unlimited
    respect_robots: bool = True


@dataclass(frozen=True)
class OutputSettings:
    """Locations of generated artefacts (database, CSV, Excel, logs)."""

    db_path: Path
    output_csv_dir: Path
    output_excel_dir: Path
    log_dir: Path
    log_level: str = "INFO"
    report_top_n: int = 10


def load_settings(env_file: Path | None = None) -> Settings:
    """Build :class:`Settings` from environment variables / the ``.env`` file.

    ``env_file`` defaults to ``<project root>/.env`` when it exists. Missing
    variables fall back to documented defaults, so the pipeline runs without
    any configuration at all.
    """
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    base_url = os.getenv("TARGET_BASE_URL", "https://books.toscrape.com/").strip()
    if not base_url:
        raise ValueError("TARGET_BASE_URL is configured but empty")

    scraper = ScraperSettings(
        base_url=base_url,
        headless=_env_bool("BROWSER_HEADLESS", True),
        navigation_timeout_seconds=_env_float("NAVIGATION_TIMEOUT_SECONDS", 30.0),
        request_delay_seconds=_env_float("REQUEST_DELAY_SECONDS", 1.0),
        page_load_retries=_env_int("PAGE_LOAD_RETRIES", 1),
        max_pages_per_category=_env_int("MAX_PAGES_PER_CATEGORY", 0),
        max_categories=_env_int("MAX_CATEGORIES", 0),
        max_products=_env_int("MAX_PRODUCTS", 0),
        respect_robots=_env_bool("RESPECT_ROBOTS", True),
    )
    output = OutputSettings(
        db_path=_resolve(os.getenv("DB_PATH", "data/products.db")),
        output_csv_dir=_resolve(os.getenv("OUTPUT_CSV_DIR", "output/csv")),
        output_excel_dir=_resolve(os.getenv("OUTPUT_EXCEL_DIR", "output/excel")),
        log_dir=_resolve(os.getenv("LOG_DIR", "logs")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        report_top_n=_env_int("REPORT_TOP_N", 10),
    )
    scheduler = SchedulerSettings(
        interval_minutes=_env_int("SCHEDULE_INTERVAL_MINUTES", 60),
        max_runs=_env_int("SCHEDULE_MAX_RUNS", 0),
    )

    settings = Settings(scraper=scraper, output=output, scheduler=scheduler)
    settings.output.log_dir.mkdir(parents=True, exist_ok=True)
    settings.output.output_csv_dir.mkdir(parents=True, exist_ok=True)
    settings.output.output_excel_dir.mkdir(parents=True, exist_ok=True)
    settings.output.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def configure_logging(settings: Settings) -> None:
    """Configure console + rotating file logging for the whole application."""
    level = getattr(logging, settings.output.log_level, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicated handlers when called more than once (e.g. tests).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.output.log_dir / "pipeline.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Third-party libraries can be very chatty at DEBUG level.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


@dataclass(frozen=True)
class SchedulerSettings:
    """Optional scheduled execution configuration."""

    interval_minutes: int = 60
    max_runs: int = 0  # 0 = run indefinitely


@dataclass(frozen=True)
class Settings:
    """Top-level application settings aggregate."""

    scraper: ScraperSettings
    output: OutputSettings
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)

    @property
    def base_url(self) -> str:
        return self.scraper.base_url
