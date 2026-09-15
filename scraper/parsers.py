"""Website-specific parsing for books.toscrape.com.

Pure extraction functions that turn a loaded Playwright page into structured
records. Every product is parsed defensively: a missing optional field degrades
to ``None`` while a product without its required fields is reported as a
parser error instead of silently corrupting the dataset.

Site facts (verified against the live HTML):
* products live in ``article.product_pod`` elements
* title  -> ``h3 a[title]`` attribute (fallback: ``img[alt]``)
* price  -> ``p.price_color`` text, e.g. ``"£51.77"``
* availability -> ``p.instock.availability`` text, e.g. ``"In stock"``
* rating -> ``p.star-rating`` class, e.g. ``"star-rating Three"`` (1-5 stars)
* pagination -> ``ul.pager li.next a[href]`` (absent on the last page)
* categories -> nested ``div.side_categories ul ul a`` links
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from playwright.sync_api import Locator, Page

from data.models import ProductRecord
from utils.logger import get_logger

logger = get_logger(__name__)

# Currency symbols seen on price tags -> ISO-4217 code. Unknown symbols are
# kept as-is rather than guessed.
CURRENCY_SYMBOLS = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "₹": "INR",
    "¥": "JPY",
}

_RATING_WORDS = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5,
}

_PRICE_RE = re.compile(r"([^\d.,\s]*?)\s*([\d.,]+)")


@dataclass(frozen=True)
class Category:
    """A product category listing page on the target site."""

    name: str
    url: str


def parse_price(text: str) -> tuple[float | None, str | None]:
    """Split a raw price string like ``"£51.77"`` into (amount, currency).

    Returns ``(None, None)`` when no numeric amount can be extracted.
    """
    match = _PRICE_RE.search(text or "")
    if not match:
        return None, None
    symbol = match.group(1).strip()
    amount_raw = match.group(2).replace(",", "").replace(" ", "")
    try:
        amount = float(amount_raw)
    except ValueError:
        return None, None
    currency = CURRENCY_SYMBOLS.get(symbol, symbol or None)
    return amount, currency


def parse_rating(class_attribute: str | None) -> int | None:
    """Map a ``star-rating One..Five`` class value to a 1-5 integer."""
    if not class_attribute:
        return None
    for word, value in _RATING_WORDS.items():
        if re.search(rf"\b{word}\b", class_attribute, re.IGNORECASE):
            return value
    return None


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_categories(page: Page, base_url: str) -> list[Category]:
    """Extract product categories from the sidebar of the home page.

    The sidebar nests real product categories inside ``ul ul``; the outer
    "Books" entry (all products) is excluded so categories stay disjoint.
    Falls back to all sidebar links (minus the all-products entry) when the
    nested selector finds nothing.
    """
    categories: list[Category] = []
    seen: set[str] = set()
    links = page.locator("div.side_categories ul ul a")
    if links.count() == 0:
        logger.warning("Nested category list empty; falling back to all sidebar links")
        links = page.locator("div.side_categories a")
    for i in range(links.count()):
        link = links.nth(i)
        href = link.get_attribute("href")
        name = _clean_text(link.text_content())
        if not href or not name:
            continue
        url = urljoin(base_url, href)
        # Skip the top-level "Books" (all products) entry.
        if re.search(r"category/books_1/", url):
            continue
        if url in seen:
            continue
        seen.add(url)
        categories.append(Category(name=name, url=url))
    return categories


def _parse_product(article: Locator, category: str, page_url: str) -> ProductRecord:
    """Parse a single ``article.product_pod`` element.

    Relative hrefs are resolved against *page_url* (the URL of the listing
    page), matching how browsers resolve them. ``count()`` guards are used
    for every optional element so a missing element never triggers a locator
    wait/timeout.
    """
    title_link = article.locator("h3 a")
    href = title_link.first.get_attribute("href") if title_link.count() else None
    name = _clean_text(
        title_link.first.get_attribute("title") if title_link.count() else None
    )
    image = article.locator("img.thumbnail")
    if not name and image.count():
        name = _clean_text(image.first.get_attribute("alt"))
    if not href or not name:
        raise ValueError("product is missing a title or a link")

    url = urljoin(page_url, href)

    price: float | None = None
    currency: str | None = None
    price_tag = article.locator("p.price_color")
    price_text = _clean_text(price_tag.first.text_content()) if price_tag.count() else ""
    if price_text:
        price, currency = parse_price(price_text)

    availability = None
    stock_tag = article.locator("p.instock.availability")
    if stock_tag.count():
        availability = _clean_text(stock_tag.first.text_content()) or None

    rating: int | None = None
    rating_tag = article.locator("p.star-rating")
    if rating_tag.count():
        rating = parse_rating(rating_tag.first.get_attribute("class"))

    image_url: str | None = None
    if image.count():
        image_src = image.first.get_attribute("src")
        if image_src:
            image_url = urljoin(page_url, image_src)

    return ProductRecord(
        name=name,
        url=url,
        price=price,
        currency=currency,
        category=category,
        availability=availability,
        rating=rating,
        image_url=image_url,
        source_product_id=extract_source_id(url),
    )


def parse_products(
    page: Page, category: str, page_url: str
) -> tuple[list[ProductRecord], list[str]]:
    """Parse every product card on a listing page.

    ``page_url`` is the URL of the page being parsed and is used to resolve
    relative product links. Returns ``(records, errors)`` where *errors*
    contains one human-readable message per unparseable product card.
    Failing required fields (name/url) skip only that card; every other
    missing field degrades to ``None``.
    """
    records: list[ProductRecord] = []
    errors: list[str] = []
    articles = page.locator("article.product_pod")
    total = articles.count()
    for i in range(total):
        article = articles.nth(i)
        try:
            records.append(_parse_product(article, category, page_url))
        except Exception as exc:  # noqa: BLE001 - one bad card must not kill the page
            message = f"Failed to parse product card {i + 1}/{total}: {exc}"
            errors.append(message)
            logger.warning(message)
    return records, errors


def parse_next_href(page: Page) -> str | None:
    """Return the relative ``next`` page link, or None on the last page."""
    next_link = page.locator("ul.pager li.next a")
    if next_link.count() == 0:
        return None
    href = next_link.first.get_attribute("href")
    return _clean_text(href) or None


def extract_source_id(product_url: str) -> str | None:
    """Extract a stable product identifier from a product page URL.

    Product URLs look like ``.../catalogue/a-light-in-the-attic_1000/index.html``
    so the directory slug (``a-light-in-the-attic_1000``) is a stable key
    that stays unique even when two books share a title.
    """
    parts = [p for p in product_url.split("/") if p]
    if len(parts) < 2:
        return None
    slug = parts[-2] if parts[-1].startswith("index") else parts[-1]
    return slug or None
