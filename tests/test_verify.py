from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from ai_weekly_agent.models import (
    CategoryResearchResult,
    DateRange,
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
