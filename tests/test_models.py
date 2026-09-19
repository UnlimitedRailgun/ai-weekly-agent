from datetime import date
import json

import pytest
from pydantic import ValidationError

from openai.lib._pydantic import to_strict_json_schema

from ai_weekly_agent.models import (
    CategoryResearchResult,
    DateRange,
    FactSupport,
    NewsItem,
    Source,
)


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
    assert source.fact_support is None


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


def test_source_accepts_explicit_null_fact_support() -> None:
    payload = make_source().model_dump()
    payload["fact_support"] = None

    assert Source.model_validate(payload).fact_support is None


def test_fact_support_and_source_round_trip() -> None:
    support = FactSupport(
        summary=True, technical_detail_indices=[0, 2], benchmark=True
    )
    source = make_source().model_copy(update={"fact_support": support})

    restored = Source.model_validate_json(source.model_dump_json())

    assert restored.fact_support == support
    # Bounds belong to Verify, so index 2 is valid in the standalone model.
    assert restored.fact_support.technical_detail_indices == [0, 2]


def test_background_fact_support_is_explicit_and_empty() -> None:
    assert FactSupport(
        summary=False, technical_detail_indices=[], benchmark=False
    ).technical_detail_indices == []


@pytest.mark.parametrize(
    "indices",
    [[-1], [0, 0], [True], [False], [0.0], [1.5], ["0"], [None]],
)
def test_fact_support_rejects_invalid_technical_indices(indices: list[object]) -> None:
    with pytest.raises(ValidationError):
        FactSupport(
            summary=True, technical_detail_indices=indices, benchmark=False
        )
    with pytest.raises(ValidationError):
        FactSupport.model_validate_json(
            json.dumps(
                {
                    "summary": True, "technical_detail_indices": indices,
                    "benchmark": False,
                }
            )
        )


def test_fact_support_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FactSupport.model_validate(
            {
                "summary": True,
                "technical_detail_indices": [],
                "benchmark": False,
                "source_id": "not-part-of-the-schema",
            }
        )


@pytest.mark.parametrize("field", ["summary", "technical_detail_indices", "benchmark"])
def test_fact_support_requires_all_three_fields(field: str) -> None:
    payload = {"summary": False, "technical_detail_indices": [], "benchmark": False}
    payload.pop(field)
    with pytest.raises(ValidationError):
        FactSupport.model_validate(payload)


@pytest.mark.parametrize("field", ["summary", "benchmark"])
@pytest.mark.parametrize("value", ["true", 1, None])
def test_fact_support_flags_are_strict_booleans(field: str, value: object) -> None:
    payload = {"summary": False, "technical_detail_indices": [], "benchmark": False}
    payload[field] = value
    with pytest.raises(ValidationError):
        FactSupport.model_validate(payload)


def test_research_strict_schema_has_nullable_additive_fact_support() -> None:
    schema = to_strict_json_schema(CategoryResearchResult)
    source_schema = schema["$defs"]["Source"]
    support_schema = schema["$defs"]["FactSupport"]

    assert "fact_support" in source_schema["required"]
    assert source_schema["properties"]["fact_support"]["anyOf"] == [
        {"$ref": "#/$defs/FactSupport"}, {"type": "null"}
    ]
    assert set(support_schema["required"]) == {
        "summary", "technical_detail_indices", "benchmark"
    }
    assert support_schema["additionalProperties"] is False
    assert support_schema["properties"]["summary"]["type"] == "boolean"
    assert support_schema["properties"]["benchmark"]["type"] == "boolean"
    assert support_schema["properties"]["technical_detail_indices"]["items"] == {
        "minimum": 0, "type": "integer"
    }
