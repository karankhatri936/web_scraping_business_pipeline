"""Optional scheduled execution with APScheduler.

``run_scheduler`` builds a blocking scheduler whose single job runs the
existing pipeline (``pipeline.run_pipeline``) - no application logic is
duplicated here. ``python main.py schedule`` is the CLI entry point.
"""

from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import Settings
from utils.exceptions import SchedulerError
from utils.logger import get_logger

logger = get_logger(__name__)

JOB_ID = "product_pipeline"


def _max_runs_wrapper(
    job: Callable[[], None], max_runs: int, scheduler: BlockingScheduler
) -> Callable[[], None]:
    """Wrap *job* so the scheduler stops after ``max_runs`` executions."""
    state = {"count": 0}

    def wrapped() -> None:
        state["count"] += 1
        try:
            job()
        finally:
            if state["count"] >= max_runs:
                logger.info(
                    "Maximum scheduled runs (%d) reached; stopping scheduler",
                    max_runs,
                )
                scheduler.shutdown(wait=False)

    return wrapped


def build_scheduler(
    settings: Settings,
    job: Callable[[], None],
    interval_minutes: int | None = None,
    max_runs: int | None = None,
) -> BlockingScheduler:
    """Create and configure a scheduler (does NOT start it).

    Parameters
    ----------
    job:
        Callable executed on every tick (normally ``pipeline.run_pipeline``).
    interval_minutes / max_runs:
        Optional overrides; default to the configured settings values.
    """
    interval = (
        interval_minutes
        if interval_minutes is not None
        else settings.scheduler.interval_minutes
    )
    runs = max_runs if max_runs is not None else settings.scheduler.max_runs
    if interval <= 0:
        raise SchedulerError(
            f"SCHEDULE_INTERVAL_MINUTES must be positive (got {interval})"
        )

    scheduler = BlockingScheduler(
        job_defaults={
            # Never let two pipeline runs overlap (duplicate-jobs guard).
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 300,
        }
    )
    if runs:
        job = _max_runs_wrapper(job, runs, scheduler)
    # Idempotent: re-adding the same job id replaces a stale registration
    # instead of stacking duplicate jobs.
    scheduler.add_job(
        job,
        trigger=IntervalTrigger(minutes=interval),
        id=JOB_ID,
        name="web scraping pipeline run",
        replace_existing=True,
    )
    logger.info(
        "Scheduler configured: pipeline runs every %d minute(s)%s",
        interval,
        f" for at most {runs} run(s)" if runs else "",
    )
    return scheduler


def run_scheduler(settings: Settings) -> None:
    """Run the pipeline on a schedule until interrupted (Ctrl+C)."""
    from pipeline import run_pipeline  # imported late to avoid a cycle

    scheduler = build_scheduler(
        settings, lambda: run_pipeline(settings, logger_name=__name__)
    )
    logger.info(
        "Starting scheduler (interval=%d min). Press Ctrl+C to stop.",
        settings.scheduler.interval_minutes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested; stopping scheduler")
    except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
        raise SchedulerError(f"Scheduler failed: {exc}") from exc
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

