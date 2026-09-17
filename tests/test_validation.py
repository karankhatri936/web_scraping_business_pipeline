"""Tests for the validation layer."""

from __future__ import annotations

from data.models import ProductRecord
from data.validator import IssueType, validate_record, validate_records


def make_record(**overrides) -> ProductRecord:
    fields = {
        "name": "Test Product",
        "url": "https://books.toscrape.com/catalogue/test_1/index.html",
        "price": 10.0,
        "currency": "GBP",
        "category": "Travel",
        "availability": "In stock",
        "rating": 4,
        "image_url": "https://books.toscrape.com/media/1.jpg",
        "source_product_id": "test_1",
    }
    fields.update(overrides)
    return ProductRecord(**fields)


def test_valid_record_passes():
    result = validate_record(make_record())
    assert result.is_valid
    assert result.record is not None
    assert not result.errors


def test_missing_required_name():
    result = validate_record(make_record(name=None))
    assert not result.is_valid
    types = {i.issue_type for i in result.issues}
    assert IssueType.MISSING_REQUIRED in types
    assert result.record is None


def test_missing_required_url():
    result = validate_record(make_record(url=None))
    assert not result.is_valid


def test_invalid_url():
    result = validate_record(make_record(url="not-a-url"))
    assert not result.is_valid
    assert any(i.field_name == "url" for i in result.errors)


def test_negative_price_repaired_not_rejected():
    result = validate_record(make_record(price=-5.0))
    assert result.is_valid  # optional field repaired to None
    assert result.record.price is None
    assert any(i.field_name == "price" for i in result.errors)


def test_non_numeric_price_repaired():
    result = validate_record(make_record(price="cheap"))
    assert result.is_valid
    assert result.record.price is None


def test_invalid_rating_repaired():
    result = validate_record(make_record(rating=9))
    assert result.is_valid
    assert result.record.rating is None


def test_missing_optional_fields_only_warn():
    record = ProductRecord(name="Minimal", url="https://example.com/x")
    result = validate_record(record)
    assert result.is_valid
    missing = {
        i.field_name
        for i in result.issues
        if i.issue_type is IssueType.MISSING_OPTIONAL
    }
    assert "price" in missing and "rating" in missing and "category" in missing


def test_malformed_record_field_types():
    result = validate_record(
        make_record(price=object(), rating=None, currency=123)
    )
    assert result.is_valid  # invalid optionals repaired
    assert result.record.price is None
    assert result.record.currency is None


def test_multiple_errors_reported():
    result = validate_record(make_record(name="", url=None))
    errors = [i.field_name for i in result.errors]
    assert "name" in errors and "url" in errors


def test_input_record_not_mutated():
    record = make_record(price=-1)
    validate_record(record)
    assert record.price == -1


def test_batch_validation_split():
    good = make_record()
    bad = make_record(name=None)
    accepted, rejected = validate_records([good, bad])
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert not rejected[0].is_valid
