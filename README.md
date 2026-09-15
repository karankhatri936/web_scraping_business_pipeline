# Web Scraping → Business Data Pipeline

An end-to-end, production-style data pipeline that turns a public product
listing website into business-ready intelligence: scrape → validate → clean →
store → analyse → report (CSV + formatted Excel).

Built as a portfolio / client-ready demonstration of a *competitor and price
monitoring* workflow: it collects publicly available product data, keeps a
history of price observations in SQLite, and produces an Excel workbook that a
non-technical stakeholder can open and read.

---

## Table of contents

- [Business use case](#business-use-case)
- [Features](#features)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Installation](#installation)
- [Playwright setup](#playwright-setup)
- [Configuration](#configuration)
- [How to run](#how-to-run)
- [Scheduling](#scheduling)
- [Output files](#output-files)
- [Database](#database)
- [Testing](#testing)
- [Error handling](#error-handling)
- [Extending to another website](#extending-to-another-website)
- [Ethical and legal considerations](#ethical-and-legal-considerations)
- [Future improvements](#future-improvements)

---

## Business use case

A retailer (or a consultancy working for one) wants to monitor a competitor's
publicly listed catalogue over time:

| Question the business asks | How this pipeline answers it |
| --- | --- |
| How many products does the competitor list? | `total_products` KPI in the Excel dashboard |
| What does the average / cheapest / most expensive product cost? | price statistics and price distribution chart |
| Which category is most expensive? | `Category Analysis` sheet with average price per category |
| How is stock availability distributed? | availability breakdown chart |
| Which products are best rated? | `Top Products` sheet |
| Did prices move since the last run? | `Price Changes` sheet + `price_history` table |

Every figure in the reports is computed from data that was actually scraped.
No sales, revenue, profit or market-share numbers are invented — that
information simply does not exist on a public listing page. Fields that the
target does not publish (review counts, brand, SKU) are **not** invented
either; the dataset simply omits them.

---

## Features

**Scraping**
- Playwright (Chromium) driven, because the target renders product cards
  client-side; a real browser keeps the parser honest if the site changes.
- Site-specific parsing kept in one module (`scraper/parsers.py`) so it can be
  swapped for another target without touching the rest of the pipeline.
- Robust selectors (CSS class + attribute based), defensive per-card parsing:
  one malformed card is logged and skipped instead of failing the page.
- Configurable politeness delay, bounded retries, navigation timeout.
- `robots.txt` pre-flight check — the run aborts if the target disallows
  fetching.

**Pagination**
- Target-agnostic walker (`scraper/pagination.py`) driven by a
  `next-link` extractor, so it adapts to "next button / URL parameter" style
  pagination.
- Never relies on a hard-coded record count.
- Guards against infinite loops (repeat-URL detection), enforces configurable
  page/category/product limits, preserves records from pages that already
  succeeded when a later page fails.

**Data quality**
- Explicit validation layer that distinguishes *required-field failure*,
  *optional-field missing* and *invalid-value*.
- Pandas cleaning/transformation: header normalisation, whitespace and text
  normalisation, numeric conversion, URL canonicalisation, currency
  derivation, duplicate removal, UTC scrape timestamps and derived analytics
  columns.
- Raw source fields are preserved (`raw_price`, `scraped_at`) next to their
  cleaned/derived counterparts (`price`, `price_bucket`).

**Storage**
- SQLite with `products` (current snapshot), `price_history` (append-only
  observations) and `scrape_runs` (run bookkeeping).
- Upsert by URL so re-runs update rows instead of duplicating them; all SQL is
  parameterised.

**Analytics and reporting**
- Pandas analytics: totals, price statistics, category comparison,
  availability mix, rating summaries, top-N rankings, price movement between
  runs.
- CSV export of the cleaned dataset (UTF-8 with BOM so Excel opens it
  correctly).
- Multi-sheet Excel report via OpenPyXL: KPIs, native Excel tables with
  filters, frozen panes, number formats, four charts and report metadata.

**Operations**
- Structured logging to console + rotating file.
- Distinct exception types per failure domain and a pipeline outcome that
  reports `success` / `partial` / `no_data` / `failed` honestly.
- Optional APScheduler-based recurring execution using the same pipeline code.

---

## Architecture

```
books.toscrape.com
        │  Playwright (Chromium)
        ▼
   scraper/            browser.py · scraper.py · pagination.py · parsers.py
        │  list[ProductRecord]
        ▼
   data/               validator.py → cleaner.py → transformer.py
        │  cleaned + derived DataFrame
        ├──────────────► database/   connection.py · models.py · repository.py
        │                     ▼
        │                 SQLite (products, price_history, scrape_runs)
        ▼
   analytics/          analysis.py → KPIs / tables
        │
        ▼
   reports/            csv_report.py · excel_report.py → output/csv, output/excel
```

`pipeline.py` orchestrates the stages and owns nothing else; `main.py` is a
thin CLI. Dependencies point inward: the database layer knows nothing about
scraping, the report layer knows nothing about SQL.

---