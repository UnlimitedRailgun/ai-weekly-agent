from datetime import date

import pytest
from pydantic import ValidationError

from ai_weekly_agent.models import DateRange, NewsItem, Source


def make_source() -> Source:
    return Source(
        title="Official announcement",
        url="https://example.com/announcement",
        source_type="official",
    )


def test_valid_date_range() -> None:
    date_range = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))

    assert date_range.start == date(2026, 8, 30)
    assert date_range.end == date(2026, 9, 5)


def test_date_range_rejects_start_after_end() -> None:
    with pytest.raises(ValidationError, match="start must not be after end"):
        DateRange(start=date(2026, 9, 6), end=date(2026, 9, 5))


def test_valid_source() -> None:
    source = make_source()

    assert source.source_type == "official"
    assert source.evidence_roles is None


def test_source_accepts_and_round_trips_evidence_roles() -> None:
    source = Source(
        title="Official announcement",
        url="https://example.com/announcement",
        source_type="official",
        evidence_roles=["event", "event_date", "technical"],
    )

    restored = Source.model_validate_json(source.model_dump_json())

    assert restored == source


def test_source_rejects_invalid_evidence_role() -> None:
    with pytest.raises(ValidationError):
        Source(
            title="Official announcement",
            url="https://example.com/announcement",
            source_type="official",
            evidence_roles=["unsupported"],
        )


def test_source_rejects_duplicate_evidence_roles() -> None:
    with pytest.raises(
        ValidationError, match="evidence_roles must not contain duplicates"
    ):
        Source(
            title="Official announcement",
            url="https://example.com/announcement",
            source_type="official",
            evidence_roles=["event", "event"],
        )


def test_news_item_accepts_missing_benchmark_information() -> None:
    item = NewsItem(
        title="Example release",
        category="AI model releases",
        organization="Example Lab",
        published_date=date(2026, 9, 5),
        summary="An example development for model validation.",
        technical_details=["A documented technical detail."],
        benchmark_information=None,
        sources=[make_source()],
    )

    assert item.benchmark_information is None


def test_news_item_requires_at_least_one_source() -> None:
    with pytest.raises(ValidationError):
        NewsItem(
            title="Unsourced release",
            category="AI model releases",
            organization=None,
            published_date=None,
            summary="This candidate has no supporting source.",
            technical_details=[],
            benchmark_information=None,
            sources=[],
        )
