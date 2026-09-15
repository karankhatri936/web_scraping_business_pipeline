"""Command-line entry point for the web scraping business pipeline.

Usage::

    python main.py              # one full pipeline run (same as `run`)
    python main.py run
    python main.py schedule     # keep running on a schedule (Ctrl+C to stop)
    python main.py init-db      # only create the SQLite schema

``main.py`` only parses arguments and delegates; all logic lives in the
packages.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from config import Settings, configure_logging, load_settings
from pipeline import init_database, run_pipeline
from scheduler.scheduler import run_scheduler
from utils.exceptions import PipelineError
from utils.logger import get_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Web scraping -> business data pipeline "
        "(books.toscrape.com demo)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run the full pipeline once (default)")
    schedule = sub.add_parser("schedule", help="run the pipeline on a schedule")
    schedule.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar="MINUTES",
        help="override SCHEDULE_INTERVAL_MINUTES",
    )
    schedule.add_argument(
        "--max-runs",
        type=int,
        default=None,
        metavar="N",
        help="stop after N scheduled runs (0 = forever)",
    )
    sub.add_parser("init-db", help="create the SQLite schema and exit")
    return parser


def _settings_for_schedule(
    settings: Settings, interval: int | None, max_runs: int | None
) -> Settings:
    scheduler = replace(
        settings.scheduler,
        interval_minutes=interval if interval is not None else settings.scheduler.interval_minutes,
        max_runs=max_runs if max_runs is not None else settings.scheduler.max_runs,
    )
    return replace(settings, scheduler=scheduler)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command or "run"

    try:
        settings = load_settings()
    except ValueError as exc:
        # Logging is not configured yet - print plainly.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings)
    log = get_logger("pipeline.cli")
    log.info("Application start | command=%s", command)

    try:
        if command == "run":
            outcome = run_pipeline(settings)
            return 0 if outcome.ok else 1
        if command == "init-db":
            init_database(settings)
            log.info("Database ready at %s", settings.output.db_path)
            return 0
        if command == "schedule":
            effective = _settings_for_schedule(
                settings, getattr(args, "interval", None), getattr(args, "max_runs", None)
            )
            run_scheduler(effective)
            return 0
    except PipelineError as exc:
        log.error("Pipeline error: %s", exc)
        return 1
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        return 130
    log.error("Unknown command: %s", command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
