from datetime import date
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from openai.lib._pydantic import to_strict_json_schema

from ai_weekly_agent.models import (
    CategoryResearchResult,
    CurationAssessment,
    CuratedItem,
    CurrentFactReference,
    DateRange,
    FactSupport,
    HistoricalContext,
    HistoricalMatch,
    HistoricalStatus,
    HistoricalStory,
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


@pytest.mark.parametrize("status", ["NEW", "FOLLOW_UP", "REPEAT", "UNCERTAIN"])
def test_historical_status_accepts_only_contract_values(status: str) -> None:
    assert TypeAdapter(HistoricalStatus).validate_python(status) == status


@pytest.mark.parametrize("status", ["new", "UNKNOWN", "", None])
def test_historical_status_rejects_other_values(status: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(HistoricalStatus).validate_python(status)


@pytest.mark.parametrize(
    ("field", "index"),
    [
        ("summary", None),
        ("technical_detail", 0),
        ("technical_detail", 3),
        ("benchmark_information", None),
    ],
)
def test_current_fact_reference_accepts_supported_forms(
    field: str, index: int | None,
) -> None:
    reference = CurrentFactReference(
        field=field, technical_detail_index=index
    )

    assert reference.field == field
    assert reference.technical_detail_index == index


@pytest.mark.parametrize(
    "payload",
    [
        {"field": "technical_detail", "technical_detail_index": None},
        {"field": "summary", "technical_detail_index": 0},
        {"field": "benchmark_information", "technical_detail_index": 0},
        {"field": "technical_detail", "technical_detail_index": -1},
        {"field": "technical_detail", "technical_detail_index": True},
        {"field": "technical_detail", "technical_detail_index": "0"},
        {"field": "title", "technical_detail_index": None},
        {
            "field": "summary", "technical_detail_index": None,
            "text": "Free-form claims are forbidden.",
        },
    ],
)
def test_current_fact_reference_rejects_invalid_combinations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CurrentFactReference.model_validate(payload)


def test_historical_story_serialization_is_stable_and_preserves_item() -> None:
    item = NewsItem(
        title="Example release",
        category="AI model releases",
        organization="Example Lab",
        published_date=date(2026, 9, 5),
        summary="Exact historical summary.",
        technical_details=["Exact historical detail."],
        benchmark_information=None,
        sources=[make_source()],
    )
    story = HistoricalStory(
        history_id="history_2026-08-30_to_2026-09-05_story_001",
        report_date_range=DateRange(
            start=date(2026, 8, 30), end=date(2026, 9, 5)
        ),
        report_position=1,
        item=item,
    )

    first = story.model_dump_json()
    restored = HistoricalStory.model_validate_json(first)

    assert restored == story
    assert restored.model_dump_json() == first
    assert restored.item.model_dump(mode="json") == item.model_dump(mode="json")


def test_historical_match_requires_unique_known_reasons() -> None:
    story = HistoricalStory(
        history_id="history_2026-08-30_to_2026-09-05_story_001",
        report_date_range=DateRange(
            start=date(2026, 8, 30), end=date(2026, 9, 5)
        ),
        report_position=1,
        item=NewsItem(
            title="Example release",
            category="AI model releases",
            organization="Example Lab",
            published_date=date(2026, 9, 5),
            summary="Exact historical summary.",
            sources=[make_source()],
        ),
    )

    assert HistoricalMatch(
        story=story,
        match_reasons=["shared_source_url", "exact_title"],
    ).story == story
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        HistoricalMatch(
            story=story,
            match_reasons=["exact_title", "exact_title"],
        )
    with pytest.raises(ValidationError):
        HistoricalMatch(story=story, match_reasons=["fuzzy_similarity"])


def test_existing_news_item_payload_without_history_fields_still_parses() -> None:
    payload = {
        "title": "Legacy item",
        "category": "AI research",
        "organization": None,
        "published_date": None,
        "summary": "Existing NewsItem contracts remain unchanged.",
        "technical_details": [],
        "benchmark_information": None,
        "sources": [{
            "title": "Legacy source",
            "url": "https://example.com/legacy",
            "source_type": "official",
        }],
    }

    restored = NewsItem.model_validate(payload)

    assert restored.title == "Legacy item"
    assert restored.sources[0].fact_support is None


def current_item() -> NewsItem:
    return NewsItem(
        title="Current release",
        category="AI model releases",
        organization="Example Lab",
        published_date=date(2026, 9, 5),
        summary="Exact current summary.",
        technical_details=["Exact current detail."],
        benchmark_information="Exact current benchmark statement.",
        sources=[make_source()],
    )


def base_assessment_payload() -> dict[str, object]:
    return {
        "candidate_id": "candidate_001",
        "impact": 4,
        "technical_significance": 4,
        "novelty": 4,
        "student_relevance": 4,
        "semantic_duplicate_of": None,
    }


def prior_range() -> DateRange:
    return DateRange(start=date(2026, 8, 23), end=date(2026, 8, 29))


def test_legacy_curation_assessment_omits_nullable_historical_fields() -> None:
    assessment = CurationAssessment.model_validate(base_assessment_payload())

    assert assessment.historical_status is None
    assert assessment.historical_match_id is None
    assert assessment.material_change_refs == []


@pytest.mark.parametrize(
    "payload_update",
    [
        {
            "historical_status": "NEW",
            "historical_match_id": "history_001",
        },
        {
            "historical_status": "FOLLOW_UP",
            "historical_match_id": "history_001",
            "material_change_refs": [],
        },
        {
            "historical_status": "REPEAT",
            "historical_match_id": "history_001",
            "material_change_refs": [
                {"field": "summary", "technical_detail_index": None}
            ],
        },
        {
            "historical_status": "UNCERTAIN",
            "material_change_refs": [
                {"field": "summary", "technical_detail_index": None}
            ],
        },
        {
            "historical_status": None,
            "historical_match_id": "history_001",
        },
    ],
)
def test_curation_assessment_rejects_contradictory_historical_shape(
    payload_update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CurationAssessment.model_validate(
            {**base_assessment_payload(), **payload_update}
        )


def test_curation_assessment_accepts_all_valid_historical_shapes() -> None:
    valid_updates = [
        {"historical_status": "NEW"},
        {
            "historical_status": "FOLLOW_UP",
            "historical_match_id": "history_001",
            "material_change_refs": [
                {"field": "summary", "technical_detail_index": None}
            ],
        },
        {
            "historical_status": "REPEAT",
            "historical_match_id": "history_001",
        },
        {"historical_status": "UNCERTAIN"},
        {
            "historical_status": "UNCERTAIN",
            "historical_match_id": "history_001",
        },
    ]

    for update in valid_updates:
        assert CurationAssessment.model_validate(
            {**base_assessment_payload(), **update}
        ).historical_status == update["historical_status"]


def test_curation_assessment_rejects_duplicate_change_references() -> None:
    reference = {"field": "summary", "technical_detail_index": None}
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        CurationAssessment.model_validate(
            {
                **base_assessment_payload(),
                "historical_status": "FOLLOW_UP",
                "historical_match_id": "history_001",
                "material_change_refs": [reference, reference],
            }
        )


def test_curation_assessment_rejects_free_form_historical_prose() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CurationAssessment.model_validate(
            {
                **base_assessment_payload(),
                "what_changed": "Model-authored factual prose is forbidden.",
            }
        )


def test_legacy_curated_item_without_historical_context_still_parses() -> None:
    payload = {"item": current_item().model_dump(mode="json"), "final_score": 4.0}

    restored = CuratedItem.model_validate(payload)

    assert restored.historical_context is None


def test_valid_follow_up_context_round_trips_exact_grounded_facts() -> None:
    context = HistoricalContext(
        status="FOLLOW_UP",
        historical_match_id="history_001",
        prior_report_date_range=prior_range(),
        prior_title="Prior release",
        material_change_facts=["Exact current summary."],
    )
    curated = CuratedItem(
        item=current_item(), final_score=4.0, historical_context=context
    )

    restored = CuratedItem.model_validate_json(curated.model_dump_json())

    assert restored == curated
    assert restored.historical_context is not None
    assert restored.historical_context.material_change_facts == [
        "Exact current summary."
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "NEW",
            "historical_match_id": "history_001",
            "prior_report_date_range": prior_range(),
            "prior_title": "Prior",
        },
        {"status": "FOLLOW_UP"},
        {
            "status": "FOLLOW_UP",
            "historical_match_id": "history_001",
            "prior_report_date_range": prior_range(),
            "prior_title": "Prior",
            "material_change_facts": [],
        },
        {
            "status": "REPEAT",
            "historical_match_id": "history_001",
            "prior_report_date_range": prior_range(),
            "prior_title": "Prior",
            "material_change_facts": ["Not allowed."],
        },
        {
            "status": "UNCERTAIN",
            "historical_match_id": "history_001",
        },
        {
            "status": "UNCERTAIN",
            "material_change_facts": ["Not allowed."],
        },
    ],
)
def test_historical_context_rejects_invalid_status_combinations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        HistoricalContext.model_validate(payload)


def test_historical_context_accepts_new_and_uncertain_without_match() -> None:
    assert HistoricalContext(status="NEW").material_change_facts == []
    assert HistoricalContext(status="UNCERTAIN").historical_match_id is None


def test_selected_curated_item_rejects_repeat_context() -> None:
    repeat_context = HistoricalContext(
        status="REPEAT",
        historical_match_id="history_001",
        prior_report_date_range=prior_range(),
        prior_title="Prior release",
    )

    with pytest.raises(ValidationError, match="REPEAT cannot appear"):
        CuratedItem(
            item=current_item(),
            final_score=4.0,
            historical_context=repeat_context,
        )
