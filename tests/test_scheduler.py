"""Tests for scheduler configuration (no long-running execution)."""

from __future__ import annotations

import pytest

from scheduler.scheduler import JOB_ID, _max_runs_wrapper, build_scheduler
from utils.exceptions import SchedulerError


def test_build_scheduler_registers_single_interval_job(settings):
    calls = []
    scheduler = build_scheduler(settings, lambda: calls.append(1))
    job = scheduler.get_job(JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == 60 * settings.scheduler.interval_minutes
    assert len(scheduler.get_jobs()) == 1
    assert not scheduler.running  # not started by the builder


def test_build_scheduler_replaces_existing_job(settings):
    """Building twice must not stack duplicate jobs."""
    first = build_scheduler(settings, lambda: None)
    second = build_scheduler(settings, lambda: None)
    assert len(second.get_jobs()) == 1
    assert second.get_job(JOB_ID).id == first.get_job(JOB_ID).id


def test_invalid_interval_rejected(settings):
    with pytest.raises(SchedulerError, match="positive"):
        build_scheduler(settings, lambda: None, interval_minutes=0)


def test_interval_override(settings):
    scheduler = build_scheduler(settings, lambda: None, interval_minutes=5)
    assert scheduler.get_job(JOB_ID).trigger.interval.total_seconds() == 300


def test_max_runs_wrapper_stops_after_limit():
    class FakeScheduler:
        def __init__(self):
            self.shutdown_requested = False

        def shutdown(self, wait=False):
            self.shutdown_requested = True

    executed = []
    fake = FakeScheduler()
    job = _max_runs_wrapper(lambda: executed.append(1), 2, fake)
    job()
    assert not fake.shutdown_requested
    job()
    assert len(executed) == 2
    assert fake.shutdown_requested
    assert fake.shutdown_requested  # idempotent check of the flag
