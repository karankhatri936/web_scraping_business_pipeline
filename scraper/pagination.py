"""Generic, target-agnostic pagination walker.

The walker decides *which* page to load next and enforces safety limits; it
does not know how pages are fetched or parsed. Those concerns are injected:

* ``loader(url) -> Page | None`` — loads a page (``None`` = load failed)
* ``visitor(url, page) -> None`` — consumes a successfully loaded page

This separation keeps the walker unit-testable without a browser and allows a
different website (with a different "next page" rule) to reuse the same
safety logic via its own ``next-link`` extraction function.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PageWalkResult:
    """Statistics about one pagination walk."""

    pages_visited: list[str] = field(default_factory=list)
    pages_failed: list[str] = field(default_factory=list)
    duplicates_detected: int = 0
    # ``True`` when the walk ended before its natural end (page limit reached,
    # or the visitor asked to stop because an item limit was hit).
    stopped_early: bool = False
    stopped_on_failure: bool = False


def walk_pages(
    start_url: str,
    loader: Callable[[str], Any | None],
    visitor: Callable[[str, Any], None],
    next_href: Callable[[Any], str | None],
    max_pages: int = 0,
) -> PageWalkResult:
    """Walk a paginated listing from *start_url* until the end.

    Parameters
    ----------
    loader:
        Loads a page for a URL; returning ``None`` signals a fetch failure.
    visitor:
        Called with ``(url, page)`` for every successfully loaded page. This
        is where records are extracted and accumulated. Returning ``False``
        stops the walk early — used when an item limit has already been
        satisfied, so no further pages are requested from the server.
    next_href:
        Extracts the link to the next page from a loaded page (``None`` when
        there is no next page).
    max_pages:
        Hard safety limit; ``0`` means unlimited (not recommended in
        production).

    The walk stops when there is no next page, when the page limit is
    reached, when the visitor returns ``False``, when a URL repeats
    (infinite-loop guard), or when a page fails to load (records collected so
    far are preserved by the caller).
    """
    result = PageWalkResult()
    visited: set[str] = set()
    current: str | None = start_url

    while current:
        if max_pages and len(result.pages_visited) >= max_pages:
            logger.info(
                "Page limit of %d reached for walk starting at %s",
                max_pages,
                start_url,
            )
            result.stopped_early = True
            break

        normalized = current.split("#", 1)[0]
        if normalized in visited:
            result.duplicates_detected += 1
            logger.warning(
                "Duplicate page URL detected (%s); stopping walk to avoid a loop",
                current,
            )
            break

        page = loader(current)
        if page is None:
            logger.error("Page failed to load; stopping walk at %s", current)
            result.pages_failed.append(current)
            result.stopped_on_failure = True
            break

        visited.add(normalized)
        result.pages_visited.append(current)
        if visitor(current, page) is False:
            logger.info("Visitor stopped the walk early at %s", current)
            result.stopped_early = True
            break

        href = next_href(page)
        current = urljoin(current, href) if href else None

    logger.info(
        "Walk from %s finished: %d page(s) visited, %d failed, %d duplicate(s)",
        start_url,
        len(result.pages_visited),
        len(result.pages_failed),
        result.duplicates_detected,
    )
    return result
