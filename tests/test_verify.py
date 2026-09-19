from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from ai_weekly_agent.models import (
    CategoryResearchResult,
    DateRange,
    FactSupport,
    NewsItem,
    ResearchRun,
    Source,
)
from ai_weekly_agent.research import RESEARCH_CATEGORIES
from ai_weekly_agent.verify import (
    VerificationError,
    item_identifier,
    verify_research_run,
)


DATE_RANGE = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
CATEGORY = RESEARCH_CATEGORIES[0]


def make_source(
    *,
    url: str = "https://example.com/release",
    source_type: str = "official",
    evidence_roles: list[str] | None = None,
) -> Source:
    return Source(
        title="Release source",
        url=url,
        source_type=source_type,
        evidence_roles=evidence_roles,
    )


def make_item(
    *,
    category: str = CATEGORY,
    published_date: date | None = date(2026, 9, 2),
    benchmark_information: str | None = None,
    technical_details: list[str] | None = None,
    sources: list[Source] | None = None,
) -> NewsItem:
    return NewsItem(
        title="Example release",
        category=category,
        organization="Example Lab",
        published_date=published_date,
        summary="Example Lab released a documented system.",
        technical_details=(
            ["A source-supported technical detail."]
            if technical_details is None
            else technical_details
        ),
        benchmark_information=benchmark_information,
        sources=(
            [make_source(evidence_roles=["event", "event_date", "technical"])]
            if sources is None
            else sources
        ),
    )


def make_run(*items: NewsItem) -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            CategoryResearchResult(
                category=category,
                items=list(items) if category == CATEGORY else [],
            )
            for category in RESEARCH_CATEGORIES
        ],
    )


def codes(result: Any) -> list[str]:
    return [finding.code for finding in result.findings]


def test_item_identifier_uses_documented_one_based_positional_format() -> None:
    assert item_identifier(1, 2) == "category_01:item_002"


@pytest.mark.parametrize(
    ("category_position", "item_position"), [(0, 1), (1, 0)]
)
def test_item_identifier_rejects_non_positive_positions(
    category_position: int, item_position: int
) -> None:
    with pytest.raises(ValueError, match="positions must be positive"):
        item_identifier(category_position, item_position)


def test_complete_canonical_category_set_passes() -> None:
    result = verify_research_run(make_run())

    assert [category.category for category in result.accepted_run.categories] == list(
        RESEARCH_CATEGORIES
    )


def test_missing_category_is_run_failure() -> None:
    run = make_run()
    run.categories.pop()

    with pytest.raises(VerificationError, match="missing categories"):
        verify_research_run(run)


def test_duplicate_category_is_run_failure() -> None:
    run = make_run()
    run.categories.append(run.categories[0].model_copy(deep=True))

    with pytest.raises(VerificationError, match="duplicate categories"):
        verify_research_run(run)


def test_unsupported_category_is_run_failure() -> None:
    run = make_run()
    run.categories[-1] = CategoryResearchResult(category="unexpected", items=[])

    with pytest.raises(VerificationError, match="unsupported categories: unexpected"):
        verify_research_run(run)


def test_valid_item_with_combined_event_and_date_evidence_passes() -> None:
    result = verify_research_run(make_run(make_item()))

    assert len(result.accepted_run.categories[0].items) == 1
    assert result.rejected_item_ids == []


def test_valid_item_can_combine_evidence_across_multiple_sources() -> None:
    item = make_item(
        sources=[
            make_source(
                url="https://example.com/event", evidence_roles=["event"]
            ),
            make_source(
                url="https://example.com/date-and-details",
                evidence_roles=["event_date", "technical"],
            ),
        ]
    )

    result = verify_research_run(make_run(item))

    assert len(result.accepted_run.categories[0].items[0].sources) == 2


def test_item_with_only_invalid_urls_is_rejected() -> None:
    item = make_item(sources=[make_source(url="not-a-url")])

    result = verify_research_run(make_run(item))

    assert result.rejected_item_ids == ["category_01:item_001"]
    unusable = next(
        finding
        for finding in result.findings
        if finding.code == "unusable_source_removed"
    )
    no_source = next(
        finding
        for finding in result.findings
        if finding.code == "no_usable_source"
    )
    assert unusable.severity == "warning"
    assert no_source.severity == "hard_failure"


def test_invalid_source_is_removed_while_valid_source_survives() -> None:
    valid = make_source(evidence_roles=["event", "event_date", "technical"])
    item = make_item(sources=[make_source(url="not-a-url"), valid])

    result = verify_research_run(make_run(item))

    accepted = result.accepted_run.categories[0].items[0]
    assert accepted.sources == [valid]
    assert "unusable_source_removed" in codes(result)
    assert result.rejected_item_ids == []


def test_normalized_duplicate_source_is_removed_deterministically() -> None:
    first = make_source(
        url="https://EXAMPLE.com/release/#details",
        evidence_roles=["event", "event_date", "technical"],
    )
    duplicate = make_source(
        url="https://example.com/release/",
        evidence_roles=["event", "event_date", "technical"],
    )

    result = verify_research_run(make_run(make_item(sources=[first, duplicate])))

    accepted_sources = result.accepted_run.categories[0].items[0].sources
    assert [source.url for source in accepted_sources] == [
        "https://example.com/release"
    ]
    assert "source_url_normalized" in codes(result)
    assert "duplicate_source_removed" in codes(result)


def test_category_mismatch_rejects_item() -> None:
    result = verify_research_run(make_run(make_item(category=RESEARCH_CATEGORIES[1])))

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "category_mismatch" in codes(result)


def test_known_out_of_range_date_rejects_item() -> None:
    result = verify_research_run(
        make_run(make_item(published_date=date(2026, 8, 29)))
    )

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "event_date_out_of_range" in codes(result)


def test_role_aware_item_without_event_evidence_is_rejected() -> None:
    item = make_item(
        sources=[make_source(evidence_roles=["event_date", "technical"])]
    )

    result = verify_research_run(make_run(item))

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "event_evidence_missing" in codes(result)


def test_known_date_without_event_date_evidence_is_rejected() -> None:
    item = make_item(sources=[make_source(evidence_roles=["event", "technical"])])

    result = verify_research_run(make_run(item))

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "event_date_evidence_missing" in codes(result)


def test_explicit_benchmark_information_requires_benchmark_evidence() -> None:
    item = make_item(
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[
            make_source(evidence_roles=["event", "event_date", "technical"])
        ],
    )

    result = verify_research_run(make_run(item))

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "benchmark_evidence_missing" in codes(result)


def test_benchmark_evidence_accepts_explicit_benchmark_information() -> None:
    item = make_item(
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[
            make_source(
                evidence_roles=["event", "event_date", "technical", "benchmark"]
            )
        ],
    )

    result = verify_research_run(make_run(item))

    assert len(result.accepted_run.categories[0].items) == 1
    assert "benchmark_evidence_missing" not in codes(result)


def test_legacy_v01_data_parses_warns_and_remains_accepted() -> None:
    data = make_run(make_item()).model_dump(mode="json")
    for category in data["categories"]:
        for item in category["items"]:
            for source in item["sources"]:
                source.pop("evidence_roles")
    legacy_run = ResearchRun.model_validate(data)

    result = verify_research_run(legacy_run)

    assert legacy_run.categories[0].items[0].sources[0].evidence_roles is None
    assert len(result.accepted_run.categories[0].items) == 1
    assert "legacy_evidence_roles" in codes(result)
    assert result.rejected_item_ids == []


def test_legacy_benchmark_claim_is_not_rejected_for_missing_role_metadata() -> None:
    item = make_item(
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[make_source(evidence_roles=None)],
    )

    result = verify_research_run(make_run(item))

    assert "legacy_evidence_roles" in codes(result)
    assert "benchmark_evidence_missing" not in codes(result)
    assert result.rejected_item_ids == []


def test_unknown_date_warns_but_remains_accepted() -> None:
    item = make_item(
        published_date=None,
        sources=[make_source(evidence_roles=["event", "technical"])],
    )

    result = verify_research_run(make_run(item))

    finding = next(
        finding
        for finding in result.findings
        if finding.code == "unknown_event_date"
    )
    assert finding.severity == "warning"
    assert result.rejected_item_ids == []


def test_all_secondary_sources_warn_but_item_remains_accepted() -> None:
    item = make_item(
        sources=[
            make_source(
                source_type="secondary",
                evidence_roles=["event", "event_date", "technical"],
            )
        ]
    )

    result = verify_research_run(make_run(item))

    assert "secondary_sources_only" in codes(result)
    assert result.rejected_item_ids == []


def test_technical_details_without_technical_evidence_warns() -> None:
    item = make_item(
        sources=[make_source(evidence_roles=["event", "event_date"])]
    )

    result = verify_research_run(make_run(item))

    assert "technical_evidence_missing" in codes(result)
    assert result.rejected_item_ids == []


def test_warning_only_item_remains_and_hard_failure_is_filtered() -> None:
    warning_item = make_item(published_date=None)
    rejected_item = make_item(
        sources=[make_source(url="file:///tmp/not-supported")]
    )
    run = make_run(warning_item, rejected_item)

    result = verify_research_run(run)

    assert len(result.accepted_run.categories[0].items) == 1
    assert result.rejected_item_ids == ["category_01:item_002"]


def test_multiple_rejections_preserve_deterministic_item_ids() -> None:
    run = make_run(
        make_item(sources=[make_source(url="invalid-one")]),
        make_item(sources=[make_source(url="invalid-two")]),
    )

    result = verify_research_run(run)

    assert result.rejected_item_ids == [
        "category_01:item_001",
        "category_01:item_002",
    ]


def test_verification_never_mutates_original_research_run() -> None:
    run = make_run(
        make_item(
            sources=[
                make_source(url="https://EXAMPLE.com/release/#details"),
                make_source(url="invalid"),
            ]
        )
    )
    original_before = deepcopy(run.model_dump(mode="python"))

    result = verify_research_run(run)

    assert run.model_dump(mode="python") == original_before
    assert result.accepted_run is not run
    assert result.accepted_run.categories[0] is not run.categories[0]


def test_repeated_verification_is_deterministic() -> None:
    run = make_run(
        make_item(
            sources=[
                make_source(
                    url="https://EXAMPLE.com/release/#details",
                    evidence_roles=["event", "event_date", "technical"],
                )
            ]
        )
    )

    first = verify_research_run(run)
    second = verify_research_run(run)

    assert first == second


def supported_source(
    *,
    url: str = "https://example.com/release",
    source_type: str = "official",
    roles: list[str] | None = None,
    summary: bool = True,
    indices: list[int] | None = None,
    benchmark: bool = False,
) -> Source:
    return Source(
        title="Explicit evidence",
        url=url,
        source_type=source_type,
        evidence_roles=(
            ["event", "event_date", "technical"] if roles is None else roles
        ),
        fact_support=FactSupport(
            summary=summary,
            technical_detail_indices=[0] if indices is None else indices,
            benchmark=benchmark,
        ),
    )


def strict_result(item: NewsItem) -> Any:
    return verify_research_run(make_run(item), require_provenance=True)


@pytest.mark.parametrize("source_type", ["official", "paper", "github", "UNIVERSITY"])
def test_strict_primary_event_date_and_detail_support_passes(
    source_type: str,
) -> None:
    item = make_item(sources=[supported_source(source_type=source_type)])
    result = strict_result(item)

    assert result.rejected_item_ids == []
    assert result.accepted_run.categories[0].items[0] == item
    assert "legacy_fact_support" not in codes(result)
    assert "legacy_evidence_roles" not in codes(result)


def test_new_metadata_activates_provenance_without_keyword() -> None:
    run = make_run(make_item(sources=[supported_source()]))

    assert verify_research_run(run) == verify_research_run(
        run, require_provenance=True
    )


def test_strict_event_and_date_can_have_separate_primary_sources() -> None:
    item = make_item(
        technical_details=[],
        sources=[
            supported_source(roles=["event"], indices=[]),
            supported_source(
                url="https://example.com/date", roles=["event_date"],
                summary=False, indices=[],
            ),
        ],
    )
    assert strict_result(item).rejected_item_ids == []


def test_strict_primary_background_does_not_rescue_secondary_summary() -> None:
    item = make_item(
        published_date=None,
        technical_details=[],
        sources=[
            supported_source(roles=["background"], summary=False, indices=[]),
            supported_source(
                url="https://news.example/event", source_type="secondary",
                roles=["event"], indices=[],
            ),
        ],
    )
    result = strict_result(item)

    assert result.rejected_item_ids == ["category_01:item_001"]
    assert "event_evidence_missing" in codes(result)


def test_summary_support_without_event_role_is_contradictory() -> None:
    item = make_item(
        sources=[supported_source(roles=["event_date", "technical"])]
    )
    result = strict_result(item)

    assert "event_evidence_missing" in codes(result)
    assert "fact_support_inconsistent" in codes(result)
    inconsistent = next(
        f for f in result.findings if f.code == "fact_support_inconsistent"
    )
    assert inconsistent.severity == "hard_failure"
    assert inconsistent.source_url == item.sources[0].url


def test_event_role_alone_is_not_explicit_summary_support() -> None:
    result = strict_result(make_item(sources=[supported_source(summary=False)]))

    assert "event_evidence_missing" in codes(result)
    assert result.rejected_item_ids


@pytest.mark.parametrize("date_type", ["secondary", "benchmark", "archive"])
def test_known_date_requires_primary_date_classification(date_type: str) -> None:
    item = make_item(
        sources=[
            supported_source(roles=["event", "technical"]),
            supported_source(
                url="https://example.com/date", source_type=date_type,
                roles=["event_date"], summary=False, indices=[],
            ),
        ],
    )
    result = strict_result(item)

    assert "event_date_evidence_missing" in codes(result)
    assert result.rejected_item_ids


def test_strict_unknown_date_warns_without_inference() -> None:
    item = make_item(
        published_date=None,
        sources=[supported_source(roles=["event", "technical"])],
    )
    result = strict_result(item)

    assert result.rejected_item_ids == []
    assert result.accepted_run.categories[0].items[0].published_date is None
    assert "unknown_event_date" in codes(result)


def test_one_source_can_cover_multiple_details() -> None:
    item = make_item(
        technical_details=["First detail.", "Second detail."],
        sources=[supported_source(indices=[0, 1])],
    )
    assert strict_result(item).rejected_item_ids == []


def test_multiple_sources_can_cover_one_detail_and_split_coverage() -> None:
    item = make_item(
        technical_details=["First detail.", "Second detail."],
        sources=[
            supported_source(),
            supported_source(
                url="https://example.com/spec", roles=["technical"],
                summary=False, indices=[0, 1],
            ),
        ],
    )
    assert strict_result(item).rejected_item_ids == []


def test_detail_coverage_gap_rejects_without_pruning() -> None:
    item = make_item(
        technical_details=["First detail.", "Unsupported second detail."],
        sources=[supported_source()],
    )
    snapshot = item.model_dump(mode="python")
    result = strict_result(item)

    assert result.rejected_item_ids == ["category_01:item_001"]
    finding = next(f for f in result.findings if f.code == "technical_evidence_missing")
    assert "index 1" in finding.message
    assert finding.severity == "hard_failure"
    assert item.model_dump(mode="python") == snapshot


def test_only_secondary_detail_support_is_rejected() -> None:
    item = make_item(
        sources=[
            supported_source(indices=[]),
            supported_source(
                url="https://news.example/spec", source_type="secondary",
                roles=["technical"], summary=False,
            ),
        ],
    )
    result = strict_result(item)

    assert "technical_evidence_missing" in codes(result)
    assert "event_evidence_missing" not in codes(result)
    assert result.rejected_item_ids


def test_out_of_range_reference_fails_even_if_all_details_have_other_support() -> None:
    item = make_item(
        sources=[
            supported_source(),
            supported_source(
                url="https://example.com/invalid-index", roles=["technical"],
                summary=False, indices=[1],
            ),
        ],
    )
    result = strict_result(item)

    assert result.rejected_item_ids
    assert "fact_support_inconsistent" in codes(result)
    assert "technical_evidence_missing" not in codes(result)
    assert any("index 1 is out of range" in f.message for f in result.findings)


def test_detail_support_without_technical_role_fails() -> None:
    item = make_item(sources=[supported_source(roles=["event", "event_date"])])
    result = strict_result(item)

    assert "fact_support_inconsistent" in codes(result)
    assert "technical_evidence_missing" in codes(result)
    assert result.rejected_item_ids


def test_empty_details_need_no_technical_support() -> None:
    item = make_item(
        technical_details=[],
        sources=[supported_source(roles=["event", "event_date"], indices=[])],
    )
    assert strict_result(item).rejected_item_ids == []


def test_blank_supplied_detail_is_rejected_without_rewriting() -> None:
    item = make_item(technical_details=["  "], sources=[supported_source()])
    original_details = list(item.technical_details)
    result = strict_result(item)

    assert "technical_evidence_missing" in codes(result)
    assert item.technical_details == original_details
    assert result.rejected_item_ids


@pytest.mark.parametrize(
    "evaluation_type", ["official", "paper", "github", "university", "benchmark"]
)
def test_original_evaluation_can_support_benchmark(evaluation_type: str) -> None:
    item = make_item(
        benchmark_information="Original evaluation reported 12 ms latency.",
        sources=[
            supported_source(),
            supported_source(
                url="https://evaluation.example/result",
                source_type=evaluation_type, roles=["benchmark"],
                summary=False, indices=[], benchmark=True,
            ),
        ],
    )
    assert strict_result(item).rejected_item_ids == []


@pytest.mark.parametrize("evaluation_type", ["secondary", "archive"])
def test_secondary_or_unknown_evaluation_does_not_qualify(
    evaluation_type: str,
) -> None:
    item = make_item(
        benchmark_information="A reported score was 90%.",
        sources=[
            supported_source(),
            supported_source(
                url="https://news.example/result", source_type=evaluation_type,
                roles=["benchmark"], summary=False, indices=[], benchmark=True,
            ),
        ],
    )
    result = strict_result(item)

    assert "benchmark_evidence_missing" in codes(result)
    assert result.rejected_item_ids


def test_null_benchmark_needs_no_benchmark_support() -> None:
    result = strict_result(make_item(sources=[supported_source()]))

    assert result.rejected_item_ids == []
    assert "benchmark_evidence_missing" not in codes(result)


def test_benchmark_role_without_explicit_support_is_insufficient() -> None:
    item = make_item(
        benchmark_information="Company-reported throughput was 100 tokens/s.",
        sources=[
            supported_source(roles=["event", "event_date", "technical", "benchmark"])
        ],
    )
    assert "benchmark_evidence_missing" in codes(strict_result(item))


def test_benchmark_support_without_role_fails() -> None:
    item = make_item(
        benchmark_information="Company-reported throughput was 100 tokens/s.",
        sources=[supported_source(benchmark=True)],
    )
    result = strict_result(item)

    assert "fact_support_inconsistent" in codes(result)
    assert "benchmark_evidence_missing" in codes(result)
    assert result.rejected_item_ids


@pytest.mark.parametrize("benchmark_text", [None, "", "  "])
def test_benchmark_support_without_information_fails(
    benchmark_text: str | None,
) -> None:
    item = make_item(
        benchmark_information=benchmark_text,
        sources=[
            supported_source(
                roles=["event", "event_date", "technical", "benchmark"],
                benchmark=True,
            )
        ],
    )
    result = strict_result(item)

    assert "fact_support_inconsistent" in codes(result)
    assert result.rejected_item_ids


def test_benchmark_type_cannot_support_event_date_or_product_details() -> None:
    source = supported_source(source_type="benchmark")
    result = strict_result(make_item(sources=[source]))

    assert {
        "event_evidence_missing", "event_date_evidence_missing",
        "technical_evidence_missing",
    } <= set(codes(result))
    assert result.rejected_item_ids


def test_benchmark_can_support_performance_but_not_product_specifications() -> None:
    item = make_item(
        benchmark_information="Original evaluator reported 12 ms latency.",
        sources=[
            supported_source(indices=[]),
            supported_source(
                url="https://evaluation.example/result", source_type="benchmark",
                roles=["technical", "benchmark"], summary=False, benchmark=True,
            ),
        ],
    )
    result = strict_result(item)

    assert "benchmark_evidence_missing" not in codes(result)
    assert "technical_evidence_missing" in codes(result)
    assert result.rejected_item_ids


@pytest.mark.parametrize("source_type", ["archive", "official-news", "secondary"])
def test_unknown_or_secondary_classification_cannot_support_primary_facts(
    source_type: str,
) -> None:
    source = supported_source(
        url="https://official.example/release", source_type=source_type
    )
    result = strict_result(make_item(sources=[source]))

    assert "event_evidence_missing" in codes(result)
    assert result.rejected_item_ids


@pytest.mark.parametrize("version", ["v0.1", "v0.2", "v0.3"])
@pytest.mark.parametrize("explicit_null", [False, True])
def test_legacy_raw_parses_and_warns_but_fails_explicit_strict_mode(
    version: str, explicit_null: bool,
) -> None:
    data = make_run(make_item()).model_dump(mode="json")
    source_data = data["categories"][0]["items"][0]["sources"][0]
    if not explicit_null:
        source_data.pop("fact_support")
    if version == "v0.1":
        source_data.pop("evidence_roles")
    restored = ResearchRun.model_validate(data)

    compatible = verify_research_run(restored)
    strict = verify_research_run(restored, require_provenance=True)

    assert compatible.rejected_item_ids == []
    assert "legacy_fact_support" in codes(compatible)
    assert restored.categories[0].items[0].sources[0].fact_support is None
    assert strict.rejected_item_ids == ["category_01:item_001"]
    assert "provenance_metadata_missing" in codes(strict)
    assert "legacy_fact_support" not in codes(strict)


@pytest.mark.parametrize("missing_field", ["fact_support", "evidence_roles"])
def test_partial_new_metadata_cannot_enter_legacy_bypass(missing_field: str) -> None:
    partial = supported_source(url="https://example.com/partial").model_copy(
        update={missing_field: None}
    )
    item = make_item(sources=[supported_source(), partial])
    result = verify_research_run(make_run(item))

    assert "provenance_metadata_missing" in codes(result)
    assert "legacy_evidence_roles" not in codes(result)
    assert "legacy_fact_support" not in codes(result)
    assert result.rejected_item_ids


def test_new_metadata_on_discarded_source_cannot_downgrade_item() -> None:
    item = make_item(
        sources=[
            make_source(evidence_roles=["event", "event_date", "technical"]),
            supported_source(url="invalid"),
        ],
    )
    result = verify_research_run(make_run(item))

    assert "unusable_source_removed" in codes(result)
    assert "provenance_metadata_missing" in codes(result)
    assert "legacy_fact_support" not in codes(result)
    assert result.rejected_item_ids


def test_duplicate_occurrence_cannot_contribute_hidden_fact_support() -> None:
    item = make_item(
        sources=[
            supported_source(
                url="https://EXAMPLE.com/release/#details",
                summary=False, indices=[],
            ),
            supported_source(),
        ],
    )
    result = strict_result(item)

    assert "duplicate_source_removed" in codes(result)
    assert "event_evidence_missing" in codes(result)
    assert "technical_evidence_missing" in codes(result)
    assert result.rejected_item_ids


def test_strict_background_and_secondary_context_can_remain_attached() -> None:
    item = make_item(
        sources=[
            supported_source(),
            supported_source(
                url="https://news.example/context", source_type="secondary",
                roles=["background"], summary=False, indices=[],
            ),
        ],
    )
    result = strict_result(item)

    assert result.rejected_item_ids == []
    assert len(result.accepted_run.categories[0].items[0].sources) == 2


def test_strict_background_source_still_needs_explicit_metadata() -> None:
    item = make_item(
        sources=[
            supported_source(),
            make_source(
                url="https://example.com/context", evidence_roles=["background"]
            ),
        ],
    )
    assert "provenance_metadata_missing" in codes(strict_result(item))


def test_strict_verification_preserves_facts_and_deep_copies_support() -> None:
    item = make_item(
        benchmark_information="Paper-reported latency was 12 ms.",
        technical_details=["Exact first detail.", "Exact second detail."],
        sources=[
            supported_source(
                url="https://EXAMPLE.com/release/#details",
                roles=["event", "event_date", "technical", "benchmark"],
                indices=[1, 0], benchmark=True,
            )
        ],
    )
    run = make_run(item)
    snapshot = deepcopy(run.model_dump(mode="python"))
    result = verify_research_run(run, require_provenance=True)
    accepted = result.accepted_run.categories[0].items[0]

    assert run.model_dump(mode="python") == snapshot
    assert accepted.summary == item.summary
    assert accepted.technical_details == item.technical_details
    assert accepted.benchmark_information == item.benchmark_information
    assert accepted.sources[0].url == "https://example.com/release"
    assert accepted.sources[0].fact_support is not item.sources[0].fact_support
    assert accepted.sources[0].fact_support.technical_detail_indices == [1, 0]
    assert result == verify_research_run(run, require_provenance=True)


def test_strict_empty_canonical_run_remains_valid() -> None:
    assert verify_research_run(
        make_run(), require_provenance=True
    ).rejected_item_ids == []


def test_strict_missing_roles_cannot_bypass_legacy_benchmark_failure() -> None:
    item = make_item(
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[make_source()],
    )
    compatible = verify_research_run(make_run(item))
    strict = strict_result(item)

    assert compatible.rejected_item_ids == []
    assert strict.rejected_item_ids == ["category_01:item_001"]
    assert "provenance_metadata_missing" in codes(strict)
    assert "benchmark_evidence_missing" in codes(strict)
    assert "legacy_evidence_roles" not in codes(strict)
