"""Browser manager lifecycle tests (real Chromium, offline)."""

from __future__ import annotations

import pytest

from scraper.browser import BrowserManager
from utils.exceptions import BrowserError


@pytest.fixture
def manager(settings) -> BrowserManager:
    return BrowserManager(settings.scraper)


def test_context_manager_cleans_up(manager):
    with manager as started:
        assert started.is_running
        page = started.new_page()
        page.goto("about:blank")
        page.close()
    assert not manager.is_running


def test_start_is_idempotent(manager):
    try:
        manager.start()
        manager.start()  # second call is a no-op
        assert manager.is_running
    finally:
        manager.close()


def test_close_is_idempotent(manager):
    manager.start()
    manager.close()
    manager.close()
    assert not manager.is_running


def test_new_page_before_start_raises(settings):
    cold = BrowserManager(settings.scraper)
    with pytest.raises(BrowserError, match="not started"):
        cold.new_page()


def test_new_page_after_close_raises(manager):
    manager.start()
    manager.close()
    with pytest.raises(BrowserError):
        manager.new_page()


def test_exception_inside_context_still_closes(manager):
    with pytest.raises(RuntimeError, match="boom"), manager:
        raise RuntimeError("boom")
    assert not manager.is_running
