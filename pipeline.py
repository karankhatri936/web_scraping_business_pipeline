"""Pipeline orchestration.

``run_pipeline`` wires every stage together in order:

config -> logging -> browser -> scrape -> validate -> clean/transform ->
store -> analyse -> CSV -> Excel -> summary -> cleanup

It owns *coordination only*; the stages themselves live in their packages.
Failure policy:

* scraping failures raise / return status ``failed`` - no false success
* validation rejects bad records but keeps valid ones (status ``partial``
  only when some records were rejected)
* database and report failures are logged with context; a report failure
  never discards stored data, and the outcome never claims success that
  did not happen
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.analysis import AnalysisResult, compute_analysis
from config import Settings, configure_logging
from data.cleaner import clean_products, records_to_dataframe
from data.transformer import add_derived_columns
from data.validator import validate_records
from database.connection import DatabaseConnection
from database.repository import ProductRepository
from reports.csv_report import write_products_csv
from reports.excel_report import write_excel_report
from scraper.browser import BrowserManager
from scraper.scraper import BooksToScrapeScraper
from utils.exceptions import ReportGenerationError
from utils.logger import get_logger


@dataclass
class PipelineOutcome:
    """Everything a caller (CLI, scheduler, tests) needs to know about a run."""

    status: str = "failed"  # success | partial | no_data | failed
    run_id: int | None = None
    records_scraped: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    records_stored: int = 0
    csv_path: Path | None = None
    excel_path: Path | None = None
    analysis: AnalysisResult | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"success", "partial", "no_data"}


def run_pipeline(
    settings: Settings,
    logger_name: str | None = None,
    configure_logging_: bool = True,
) -> PipelineOutcome:
    """Execute one full pipeline run and return a structured outcome."""
    if configure_logging_:
        configure_logging(settings)
    log = get_logger(logger_name or "pipeline.orchestrator")

    log.info("=" * 60)
    log.info("Pipeline starting | target=%s", settings.base_url)
    log.info("=" * 60)

    db = DatabaseConnection(settings.output.db_path)
    repo = ProductRepository(settings.output.db_path)
    outcome = PipelineOutcome()

    try:
        repo.init_db()
    except Exception as exc:  # noqa: BLE001 - surfaced below
        outcome.error = f"Database initialisation failed: {exc}"
        log.error(outcome.error)
        return outcome

    run_id = repo.start_run()
    outcome.run_id = run_id

    # ---- scrape ----------------------------------------------------------
    try:
        with BrowserManager(settings.scraper) as browser:
            scraper = BooksToScrapeScraper(settings.scraper, browser)
            records = scraper.scrape()
    except Exception as exc:  # noqa: BLE001 - any scrape failure is run-fatal
        outcome.error = f"Scraping failed: {exc}"
        log.error(outcome.error)
        _finish_run(repo, run_id, "failed", outcome)
        return outcome

    outcome.records_scraped = len(records)
    log.info("Scrape collected %d record(s)", len(records))

    # ---- validate ---------------------------------------------------------
    accepted, rejected_results = validate_records(records)
    outcome.records_accepted = len(accepted)
    outcome.records_rejected = len(rejected_results)
    if rejected_results:
        log.warning(
            "%d record(s) rejected by validation; %d accepted",
            len(rejected_results),
            len(accepted),
        )

    if not accepted:
        outcome.status = "no_data"
        outcome.error = "No valid records were collected in this run"
        log.error(outcome.error)
        _finish_run(repo, run_id, "no_data", outcome)
        return outcome

    # ---- clean + transform --------------------------------------------------
    cleaned = clean_products(records_to_dataframe(accepted))
    dataset = add_derived_columns(cleaned.frame)
    outcome.details["duplicates_removed_in_cleaning"] = cleaned.duplicates_removed

    # ---- store ---------------------------------------------------------------
    try:
        outcome.records_stored = repo.upsert_products(dataset, run_id)
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"Database storage failed: {exc}"
        log.error(outcome.error)
        _finish_run(repo, run_id, "failed", outcome)
        return outcome
    log.info("Stored/updated %d product row(s)", outcome.records_stored)

    # ---- analyse ------------------------------------------------------------
    previous = repo.get_previous_prices(run_id)
    analysis = compute_analysis(
        dataset, previous_prices=previous, top_n=settings.output.report_top_n
    )
    outcome.analysis = analysis

    # ---- reports --------------------------------------------------------------
    report_error: str | None = None
    try:
        outcome.csv_path = write_products_csv(
            dataset, settings.output.output_csv_dir
        )
    except ReportGenerationError as exc:
        report_error = str(exc)
        log.error("CSV report failed (database data is preserved): %s", exc)
    try:
        outcome.excel_path = write_excel_report(
            analysis,
            dataset,
            settings.output.output_excel_dir,
            source_url=settings.base_url,
            extra_metadata={
                "run_id": run_id,
                "records_rejected": outcome.records_rejected,
                "duplicates_removed_in_cleaning": cleaned.duplicates_removed,
                "database": str(settings.output.db_path),
            },
        )
    except ReportGenerationError as exc:
        report_error = report_error or str(exc)
        log.error("Excel report failed (database data is preserved): %s", exc)

    # ---- finish -----------------------------------------------------------------
    outcome.status = "partial" if (rejected_results or report_error) else "success"
    _finish_run(repo, run_id, outcome.status, outcome)
    log.info(
        "Pipeline finished | status=%s scraped=%d accepted=%d rejected=%d "
        "stored=%d csv=%s excel=%s",
        outcome.status,
        outcome.records_scraped,
        outcome.records_accepted,
        outcome.records_rejected,
        outcome.records_stored,
        outcome.csv_path,
        outcome.excel_path,
    )
    log.info("=" * 60)
    return outcome


def _finish_run(
    repo: ProductRepository, run_id: int, status: str, outcome: PipelineOutcome
) -> None:
    """Record run bookkeeping; bookkeeping failures must not mask the outcome."""
    try:
        repo.finish_run(
            run_id,
            status,
            {
                "records_found": outcome.records_scraped,
                "records_accepted": outcome.records_accepted,
                "records_rejected": outcome.records_rejected,
            },
        )
    except Exception as exc:  # noqa: BLE001 - log and continue
        get_logger("pipeline.orchestrator").error(
            "Could not store run bookkeeping: %s", exc
        )


def init_database(settings: Settings) -> None:
    """Create the database schema without scraping (``main.py init-db``)."""
    ProductRepository(settings.output.db_path).init_db()
