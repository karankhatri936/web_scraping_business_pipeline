"""Custom exception hierarchy.

Each pipeline layer raises (and callers handle) a specific exception type so
failures can be logged and reacted to precisely instead of using bare
``except Exception`` blocks.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for all pipeline-specific errors."""


class BrowserError(PipelineError):
    """Raised when the browser cannot be started or used."""


class PageFetchError(PipelineError):
    """Raised when a page cannot be loaded (timeout, network, HTTP error)."""


class RobotsDisallowedError(PipelineError):
    """Raised when robots.txt disallows scraping the target path."""


class DatabaseError(PipelineError):
    """Raised when database operations fail."""


class ReportGenerationError(PipelineError):
    """Raised when CSV/Excel report generation fails."""


class SchedulerError(PipelineError):
    """Raised when the scheduler cannot be configured or run."""
