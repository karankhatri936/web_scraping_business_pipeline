"""Tests for the generic pagination walker (no browser needed)."""

from __future__ import annotations

from scraper.pagination import walk_pages


def make_site(pages: dict[str, dict]) -> tuple:
    """Build loader/visitor/next_href triple from a url -> page spec map."""
    visited: list[str] = []

    def loader(url: str):
        return pages.get(url)

    def visitor(url: str, page) -> None:
        visited.append(url)
        visited.extend(page.get("records", []))

    def next_href(page):
        return page.get("next")

    return loader, visitor, next_href, visited


def test_multiple_pages_visited_in_order():
    pages = {
        "p1": {"next": "p2", "records": ["r1"]},
        "p2": {"next": "p3", "records": ["r2"]},
        "p3": {"records": ["r3"]},
    }
    loader, visitor, next_href, visited = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.pages_visited == ["p1", "p2", "p3"]
    assert result.pages_failed == []
    assert result.duplicates_detected == 0
    assert result.stopped_early is False
    assert "r1" in visited and "r3" in visited


def test_final_page_without_next_link():
    pages = {"p1": {"next": None, "records": []}}
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.pages_visited == ["p1"]


def test_empty_page_is_handled():
    pages = {"p1": {"next": "p2"}, "p2": {"records": []}}
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.pages_visited == ["p1", "p2"]


def test_duplicate_page_stops_walk():
    pages = {
        "p1": {"next": "p2"},
        "p2": {"next": "p1"},  # cycle back to the start
    }
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.duplicates_detected == 1
    assert result.pages_visited == ["p1", "p2"]  # p1 not visited twice


def test_max_pages_limit():
    pages = {f"p{i}": {"next": f"p{i + 1}"} for i in range(1, 6)}
    pages["p5"] = {"records": []}
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href, max_pages=3)
    assert result.pages_visited == ["p1", "p2", "p3"]
    assert result.stopped_early is True


def test_visitor_can_stop_the_walk():
    """A visitor returning False stops the walk before the next page loads."""
    pages = {
        "p1": {"next": "p2", "records": ["r1"]},
        "p2": {"next": "p3", "records": ["r2"]},
    }
    loaded: list[str] = []

    def loader(url):
        loaded.append(url)
        return pages.get(url)

    def visitor(url, page):
        # The walk only stops on an explicit False, so a normal truthy return
        # value (record count, etc.) never interrupts pagination.
        return False if page.get("records") == ["r1"] else None

    result = walk_pages("p1", loader, visitor, lambda page: page.get("next"))
    assert result.pages_visited == ["p1"]
    assert loaded == ["p1"]
    assert result.stopped_early is True


def test_ordinary_visitor_return_does_not_stop_the_walk():
    pages = {
        "p1": {"next": "p2", "records": ["r1"]},
        "p2": {"next": "p3", "records": ["r2"]},
        "p3": {"records": []},
    }
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.pages_visited == ["p1", "p2", "p3"]
    assert result.stopped_early is False


def test_failed_page_preserves_earlier_records():
    pages = {"p1": {"next": "p2", "records": ["r1"]}}
    loader, visitor, next_href, visited = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.stopped_on_failure is True
    assert result.pages_failed == ["p2"]
    assert "r1" in visited  # records from p1 survived


def test_fragment_only_urls_not_treated_as_new_pages():
    pages = {"p1": {"next": "p1#section", "records": []}}
    loader, visitor, next_href, _ = make_site(pages)
    result = walk_pages("p1", loader, visitor, next_href)
    assert result.duplicates_detected == 1
    assert result.pages_visited == ["p1"]
