"""Data validation for scraped product records.

The validator classifies every issue it finds so callers can react
precisely:

* ``missing_required`` - a required field (name / url) is absent or empty
  -> the record is rejected.
* ``invalid_value``    - a present field holds an unusable value. Invalid
  *optional* fields are repaired by setting them to ``None`` (the record
  stays usable); invalid *required* fields reject the record.
* ``missing_optional`` - an optional field is absent -> warning only.
* ``warning``          - informational issues that don't affect validity.

The validator never invents values; it only drops unusable ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from data.models import ProductRecord
from utils.logger import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
# The source site uses a 1-5 star scale.
RATING_MIN, RATING_MAX = 0.0, 5.0


class IssueType(str, Enum):
    MISSING_REQUIRED = "missing_required"
    INVALID_VALUE = "invalid_value"
    MISSING_OPTIONAL = "missing_optional"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found while validating a record."""

    issue_type: IssueType
    field_name: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.issue_type.value}:{self.field_name}: {self.message}"


@dataclass
class ValidationResult:
    """Outcome of validating a single record."""

    record: ProductRecord | None
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [
            i for i in self.issues if i.issue_type is not IssueType.MISSING_OPTIONAL
        ]


def _bad(field_name: str, message: str) -> ValidationIssue:
    return ValidationIssue(IssueType.INVALID_VALUE, field_name, message)


def validate_record(record: ProductRecord) -> ValidationResult:
    """Validate *record*; returns a repaired copy when recoverable.

    The input record is never mutated.
    """
    issues: list[ValidationIssue] = []
    repaired = ProductRecord(**record.to_dict())

    # ---- required fields -------------------------------------------------
    if not _non_empty_str(record.name):
        issues.append(_missing_required("name"))
    else:
        repaired.name = record.name.strip()

    if not _non_empty_str(record.url):
        issues.append(_missing_required("url"))
        url_invalid = False
    elif not _URL_RE.match(record.url.strip()):
        issues.append(_bad("url", f"not a valid http(s) URL: {record.url!r}"))
        url_invalid = True
    else:
        repaired.url = record.url.strip()
        url_invalid = False

    # ---- optional numeric fields ----------------------------------------
    if record.price is None:
        issues.append(ValidationIssue(IssueType.MISSING_OPTIONAL, "price", "not present"))
    elif not isinstance(record.price, (int, float)) or isinstance(record.price, bool):
        issues.append(_bad("price", f"non-numeric price: {record.price!r}"))
        repaired.price = None
    elif record.price < 0:
        issues.append(_bad("price", f"negative price: {record.price!r}"))
        repaired.price = None

    if record.rating is None:
        issues.append(ValidationIssue(IssueType.MISSING_OPTIONAL, "rating", "not present"))
    elif not isinstance(record.rating, (int, float)) or isinstance(record.rating, bool):
        issues.append(_bad("rating", f"non-numeric rating: {record.rating!r}"))
        repaired.rating = None
    elif not (RATING_MIN <= record.rating <= RATING_MAX):
        issues.append(
            _bad("rating", f"rating outside {RATING_MIN}-{RATING_MAX}: {record.rating!r}")
        )
        repaired.rating = None
    return _finish_text_fields(repaired, issues, record, url_invalid=url_invalid)


def _finish_text_fields(
    repaired: ProductRecord,
    issues: list[ValidationIssue],
    original: ProductRecord,
    url_invalid: bool = False,
) -> ValidationResult:
    """Validate text fields and compute the final verdict."""
    for name in ("currency", "category", "availability"):
        value = getattr(original, name)
        if value is None:
            issues.append(
                ValidationIssue(IssueType.MISSING_OPTIONAL, name, "not present")
            )
        elif not _non_empty_str(value):
            issues.append(_bad(name, f"non-string or empty value: {value!r}"))
            setattr(repaired, name, None)
        else:
            setattr(repaired, name, value.strip())

    if original.image_url is None:
        issues.append(
            ValidationIssue(IssueType.MISSING_OPTIONAL, "image_url", "not present")
        )
    elif not _non_empty_str(original.image_url):
        issues.append(
            _bad("image_url", f"non-string or empty value: {original.image_url!r}")
        )
        repaired.image_url = None
    elif not _URL_RE.match(original.image_url.strip()):
        issues.append(
            _bad("image_url", f"not a valid http(s) URL: {original.image_url!r}")
        )
        repaired.image_url = None
    else:
        repaired.image_url = original.image_url.strip()

    if original.source_product_id is None:
        issues.append(
            ValidationIssue(
                IssueType.WARNING, "source_product_id", "missing; dedup falls back to URL"
            )
        )
    elif isinstance(original.source_product_id, str) and original.source_product_id.strip():
        repaired.source_product_id = original.source_product_id.strip()
    else:
        repaired.source_product_id = None

    missing_required = any(i.issue_type is IssueType.MISSING_REQUIRED for i in issues)
    is_valid = not missing_required and not url_invalid
    result_record: ProductRecord | None = repaired if is_valid else None
    return ValidationResult(record=result_record, is_valid=is_valid, issues=issues)


def validate_records(
    records: list[ProductRecord],
) -> tuple[list[ProductRecord], list[ValidationResult]]:
    """Validate a batch; returns ``(accepted, rejected_results)``."""
    accepted: list[ProductRecord] = []
    rejected: list[ValidationResult] = []
    for record in records:
        result = validate_record(record)
        if result.is_valid:
            accepted.append(result.record)  # type: ignore[arg-type]
        else:
            rejected.append(result)
            logger.warning(
                "Rejected record %r: %s",
                record.name,
                "; ".join(str(i) for i in result.errors),
            )
    return accepted, rejected



def _missing_required(field_name: str) -> ValidationIssue:
    return ValidationIssue(
        IssueType.MISSING_REQUIRED, field_name, "required field is missing or empty"
    )


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
