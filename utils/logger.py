"""Logging helpers.

The root logging configuration itself lives in :mod:`config.configure_logging`
so that the CLI entry point controls where logs go. This module only provides
a small, consistent way for modules to obtain their logger.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for a pipeline module."""
    if not name.startswith("pipeline"):
        name = f"pipeline.{name}"
    return logging.getLogger(name)
