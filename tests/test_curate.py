from datetime import date
from typing import Any

import pytest

import ai_weekly_agent.curate as curate_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.curate import (
    MAX_CURATED_ITEMS,
    MIN_CURATED_SCORE,
    CuratorError,
    calculate_final_score,
    curate_research_run,
)
from ai_weekly_agent.models import (
    CategoryResearchResult,
    CurationAssessment,
    DateRange,
    NewsItem,
    ResearchRun,
    Source,
)


DATE_RANGE = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
MODEL = "test-model"


def configured_app() -> AppConfig:
    return AppConfig(
        openai_api_key="test-key-not-a-real-credential",
        openai_model=MODEL,
    )


def make_source(
    url: str,
    *,
    source_type: str = "official",
) -> Source:
    return Source(
        title=f"Source for {url}",
        url=url,
        source_type=source_type,
    )


def make_item(
    title: str,
    *,
    category: str = "AI model releases",
    organization: str | None = "Example Lab",
    published_date: date | None = date(2026, 9, 2),
    source_urls: tuple[str, ...] | None = None,
    source_type: str = "official",
    technical_details: list[str] | None = None,
) -> NewsItem:
    if source_urls is None:
        slug = "-".join(title.casefold().split())
        source_urls = (f"https://example.com/{slug}",)
    return NewsItem(
        title=title,
        category=category,
        organization=organization,
        published_date=published_date,
        summary=f"Summary for {title}",
        technical_details=technical_details or ["Technical detail."],
        benchmark_information=None,
        sources=[
            make_source(url, source_type=source_type) for url in source_urls
        ],
    )


def make_run(
    *category_groups: tuple[str, list[NewsItem]],
) -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            CategoryResearchResult(category=category, items=items)
            for category, items in category_groups
        ],
    )


def one_category_run(*items: NewsItem) -> ResearchRun:
    return make_run(("AI model releases", list(items)))


def assessment(
    candidate_id: str,
    *,
    scores: tuple[int, int, int, int] = (4, 4, 4, 4),
    duplicate_of: str | None = None,
) -> dict[str, Any]:
    impact, technical, novelty, relevance = scores
    return {
        "candidate_id": candidate_id,
        "impact": impact,
        "technical_significance": technical,
        "novelty": novelty,
        "student_relevance": relevance,
        "semantic_duplicate_of": duplicate_of,
    }


class FakeResponses:
    def __init__(
        self,
        assessments: list[dict[str, Any]] | None = None,
        *,
        error: Exception | None = None,
        output_parsed: object | None = None,
    ) -> None:
        self.assessments = assessments
        self.error = error
        self.output_parsed = output_parsed
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        parsed = self.output_parsed
        if parsed is None:
            parsed = {"assessments": self.assessments or []}
        return {"output_parsed": parsed}


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def client_for(*assessments: dict[str, Any]) -> FakeClient:
    return FakeClient(FakeResponses(list(assessments)))


def curate_with(
    research_run: ResearchRun,
    *assessments: dict[str, Any],
) -> tuple[list, FakeClient]:
    client = client_for(*assessments)
    result = curate_research_run(
        research_run,
        configured_app(),
        client=client,
    )
    return result, client


def test_empty_research_run_returns_without_api_call() -> None:
    responses = FakeResponses(error=AssertionError("must not be called"))
    client = FakeClient(responses)
    research_run = ResearchRun(date_range=DATE_RANGE, categories=[])

    result = curate_research_run(research_run, AppConfig(), client=client)

    assert result == []
    assert responses.calls == []


def test_curator_fallback_uses_centralized_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for(assessment("candidate_001"))
    config = configured_app()
    factory_calls: list[AppConfig] = []

    def fake_factory(received_config: AppConfig) -> FakeClient:
        factory_calls.append(received_config)
        return client

    monkeypatch.setattr(curate_module, "create_openai_client", fake_factory)

    result = curate_research_run(one_category_run(make_item("First")), config)

    assert factory_calls == [config]
    assert len(client.responses.calls) == 1
    assert len(result) == 1


def test_candidates_are_flattened_in_category_and_item_order() -> None:
    first = make_item("First model")
    second = make_item("Second model")
    third = make_item("Research result", category="AI research")
    research_run = make_run(
        ("AI model releases", [first, second]),
        ("AI research", [third]),
    )

    result, client = curate_with(
        research_run,
        assessment("candidate_001"),
        assessment("candidate_002"),
        assessment("candidate_003"),
    )

    prompt = client.responses.calls[0]["input"]
    assert prompt.index("candidate_001") < prompt.index("candidate_002")
    assert prompt.index("candidate_002") < prompt.index("candidate_003")
    assert {item.item.title for item in result} == {
        first.title,
        second.title,
        third.title,
    }


def test_normalized_title_duplicates_keep_more_sources() -> None:
    first = make_item("Example Release!", source_urls=("https://a.example",))
    second = make_item(
        "  example release  ",
        source_urls=("https://b.example", "https://c.example"),
    )

    result, client = curate_with(
        one_category_run(first, second),
        assessment("candidate_002"),
    )

    assert len(client.responses.calls) == 1
    assert "candidate_001" not in client.responses.calls[0]["input"]
    assert result[0].item is second


def test_shared_normalized_source_duplicate_keeps_richer_item() -> None:
    first = make_item(
        "Launch announcement",
        source_urls=("https://example.com/release/",),
        technical_details=["Short."],
    )
    second = make_item(
        "Product is released",
        source_urls=("https://EXAMPLE.com/release#launch",),
        technical_details=["A substantially richer technical explanation."],
    )

    result, _ = curate_with(
        one_category_run(first, second),
        assessment("candidate_002"),
    )

    assert [item.item.title for item in result] == [second.title]


def test_shared_source_does_not_merge_different_organizations() -> None:
    shared_url = ("https://example.com/industry-roundup",)
    first = make_item("Lab A launch", source_urls=shared_url, organization="Lab A")
    second = make_item("Lab B launch", source_urls=shared_url, organization="Lab B")

    result, _ = curate_with(
        one_category_run(first, second),
        assessment("candidate_001"),
        assessment("candidate_002"),
    )

    assert len(result) == 2


def test_exact_duplicate_tie_break_prefers_known_date() -> None:
    undated = make_item("Same event", published_date=None)
    dated = make_item("same event", published_date=date(2026, 9, 2))

    result, _ = curate_with(
        one_category_run(undated, dated),
        assessment("candidate_002"),
    )

    assert result[0].item is dated


def test_exact_duplicate_tie_break_prefers_richer_details() -> None:
    shorter = make_item("Same event", technical_details=["Short."])
    richer = make_item(
        "same event",
        technical_details=["A much more detailed technical explanation."],
    )

    result, _ = curate_with(
        one_category_run(shorter, richer),
        assessment("candidate_002"),
    )

    assert result[0].item is richer


def test_exact_duplicate_final_tie_prefers_earlier_input() -> None:
    first = make_item("Same event", source_urls=("https://a.example",))
    second = make_item("same event", source_urls=("https://b.example",))

    result, _ = curate_with(
        one_category_run(first, second),
        assessment("candidate_001"),
    )

    assert result[0].item is first


def test_hard_filters_run_before_api_assessment() -> None:
    no_sources = make_item("No sources").model_copy(update={"sources": []})
    empty_title = make_item("Temporary").model_copy(update={"title": " !!! "})
    outside = make_item("Outside", published_date=date(2026, 8, 29))
    valid = make_item("Valid")

    result, client = curate_with(
        one_category_run(no_sources, empty_title, outside, valid),
        assessment("candidate_004"),
    )

    prompt = client.responses.calls[0]["input"]
    assert "candidate_001" not in prompt
    assert "candidate_002" not in prompt
    assert "candidate_003" not in prompt
    assert [item.item.title for item in result] == [valid.title]


def test_configured_model_is_used() -> None:
    _, client = curate_with(
        one_category_run(make_item("Release")),
        assessment("candidate_001"),
    )

    assert client.responses.calls[0]["model"] == MODEL


def test_curation_supplies_no_tools_or_web_search() -> None:
    _, client = curate_with(
        one_category_run(make_item("Release")),
        assessment("candidate_001"),
    )

    call = client.responses.calls[0]
    assert "tools" not in call
    assert "tool_choice" not in call
    assert "web_search" not in call["input"]
    assert "Do not browse, search, call tools" in call["input"]


def test_multiple_candidates_use_one_llm_request() -> None:
    items = [make_item(f"Release {index}") for index in range(3)]

    _, client = curate_with(
        one_category_run(*items),
        *(assessment(f"candidate_{index:03d}") for index in range(1, 4)),
    )

    assert len(client.responses.calls) == 1


def test_candidate_ids_and_evidence_are_in_prompt() -> None:
    item = make_item("Specific release")

    _, client = curate_with(
        one_category_run(item),
        assessment("candidate_001"),
    )

    prompt = client.responses.calls[0]["input"]
    assert '"candidate_id": "candidate_001"' in prompt
    assert '"title": "Specific release"' in prompt
    assert '"sources"' in prompt


def test_one_candidate_still_receives_quality_assessment() -> None:
    result, client = curate_with(
        one_category_run(make_item("Only release")),
        assessment("candidate_001"),
    )

    assert len(client.responses.calls) == 1
    assert len(result) == 1


def test_structured_assessments_parse_into_curated_items() -> None:
    result, client = curate_with(
        one_category_run(make_item("Release")),
        assessment("candidate_001", scores=(5, 4, 4, 3)),
    )

    assert client.responses.calls[0]["text_format"].__name__ == (
        "_CurationResponse"
    )
    assert result[0].final_score == 4.0


def test_complete_assessment_set_is_accepted_in_any_order() -> None:
    first = make_item("First")
    second = make_item("Second")

    result, _ = curate_with(
        one_category_run(first, second),
        assessment("candidate_002"),
        assessment("candidate_001"),
    )

    assert [item.item.title for item in result] == [first.title, second.title]


def test_unknown_assessment_candidate_id_fails() -> None:
    with pytest.raises(CuratorError, match="unknown candidate ID"):
        curate_with(
            one_category_run(make_item("Release")),
            assessment("candidate_999"),
        )


def test_missing_assessment_fails() -> None:
    with pytest.raises(CuratorError, match="omitted candidate IDs: candidate_002"):
        curate_with(
            one_category_run(make_item("First"), make_item("Second")),
            assessment("candidate_001"),
        )


def test_duplicate_assessment_fails() -> None:
    with pytest.raises(CuratorError, match="duplicate candidate ID"):
        curate_with(
            one_category_run(make_item("Release")),
            assessment("candidate_001"),
            assessment("candidate_001"),
        )


def test_self_semantic_duplicate_fails() -> None:
    with pytest.raises(CuratorError, match="duplicate of itself"):
        curate_with(
            one_category_run(make_item("Release")),
            assessment("candidate_001", duplicate_of="candidate_001"),
        )


def test_unknown_semantic_duplicate_target_fails() -> None:
    with pytest.raises(CuratorError, match="unknown semantic duplicate"):
        curate_with(
            one_category_run(make_item("Release")),
            assessment("candidate_001", duplicate_of="candidate_999"),
        )


@pytest.mark.parametrize("invalid_score", [0, 6])
def test_assessment_score_bounds_are_enforced(invalid_score: int) -> None:
    invalid = assessment("candidate_001")
    invalid["impact"] = invalid_score

    with pytest.raises(CuratorError, match="Invalid structured curation response"):
        curate_with(one_category_run(make_item("Release")), invalid)


def test_equal_weight_final_score() -> None:
    value = calculate_final_score(
        CurationAssessment(
            candidate_id="candidate_001",
            impact=5,
            technical_significance=4,
            novelty=3,
            student_relevance=2,
            semantic_duplicate_of=None,
        )
    )

    assert value == 3.5


def test_semantic_duplicate_loser_is_removed() -> None:
    first = make_item("Official launch")
    second = make_item("Coverage of launch")

    result, _ = curate_with(
        one_category_run(first, second),
        assessment("candidate_001", scores=(5, 5, 5, 5)),
        assessment(
            "candidate_002",
            scores=(4, 4, 4, 4),
            duplicate_of="candidate_001",
        ),
    )

    assert [item.item.title for item in result] == [first.title]


def test_higher_scoring_semantic_duplicate_survives_reference_direction() -> None:
    stronger = make_item("Stronger coverage")
    referenced = make_item("Referenced coverage")

    result, _ = curate_with(
        one_category_run(stronger, referenced),
        assessment(
            "candidate_001",
            scores=(5, 5, 5, 5),
            duplicate_of="candidate_002",
        ),
        assessment("candidate_002", scores=(4, 4, 4, 4)),
    )

    assert [item.item.title for item in result] == [stronger.title]


def test_semantic_duplicate_tie_prefers_primary_source() -> None:
    secondary = make_item("Secondary", source_type="secondary")
    primary = make_item("Primary", source_type="official")

    result, _ = curate_with(
        one_category_run(secondary, primary),
        assessment("candidate_001", duplicate_of="candidate_002"),
        assessment("candidate_002"),
    )

    assert [item.item.title for item in result] == [primary.title]


def test_semantic_duplicate_cycle_resolves_deterministically() -> None:
    first = make_item("First account")
    second = make_item("Second account")

    result, _ = curate_with(
        one_category_run(first, second),
        assessment(
            "candidate_001",
            scores=(5, 5, 5, 5),
            duplicate_of="candidate_002",
        ),
        assessment(
            "candidate_002",
            scores=(4, 4, 4, 4),
            duplicate_of="candidate_001",
        ),
    )

    assert [item.item.title for item in result] == [first.title]


def test_quality_threshold_removes_weak_items() -> None:
    strong = make_item("Strong")
    weak = make_item("Weak")

    result, _ = curate_with(
        one_category_run(strong, weak),
        assessment("candidate_001", scores=(4, 4, 4, 4)),
        assessment("candidate_002", scores=(3, 3, 3, 3)),
    )

    assert MIN_CURATED_SCORE == 3.25
    assert [item.item.title for item in result] == [strong.title]


def test_fewer_than_eight_strong_items_are_returned_without_filler() -> None:
    items = [make_item(f"Strong {index}") for index in range(3)]

    result, _ = curate_with(
        one_category_run(*items),
        *(assessment(f"candidate_{index:03d}") for index in range(1, 4)),
    )

    assert len(result) == 3


def test_maximum_curated_item_count_is_twelve() -> None:
    items = [make_item(f"Strong {index:02d}") for index in range(15)]

    result, _ = curate_with(
        one_category_run(*items),
        *(assessment(f"candidate_{index:03d}") for index in range(1, 16)),
    )

    assert MAX_CURATED_ITEMS == 12
    assert len(result) == 12
    assert [item.item.title for item in result] == [
        item.title for item in items[:12]
    ]


def test_final_order_is_score_then_stable_input_order() -> None:
    medium_first = make_item("Medium first")
    high = make_item("High")
    medium_second = make_item("Medium second")

    result, _ = curate_with(
        one_category_run(medium_first, high, medium_second),
        assessment("candidate_001", scores=(4, 4, 4, 4)),
        assessment("candidate_002", scores=(5, 5, 5, 5)),
        assessment("candidate_003", scores=(4, 4, 4, 4)),
    )

    assert [item.item.title for item in result] == [
        high.title,
        medium_first.title,
        medium_second.title,
    ]


def test_near_tie_diversity_preference_is_deterministic() -> None:
    model_first = make_item("Model first")
    model_second = make_item("Model second")
    research = make_item("Research", category="AI research")
    research_run = make_run(
        ("AI model releases", [model_first, model_second]),
        ("AI research", [research]),
    )

    result, _ = curate_with(
        research_run,
        assessment("candidate_001", scores=(5, 5, 5, 5)),
        assessment("candidate_002", scores=(5, 5, 5, 5)),
        assessment("candidate_003", scores=(5, 5, 5, 4)),
    )

    assert [item.item.title for item in result] == [
        model_first.title,
        research.title,
        model_second.title,
    ]


def test_api_exception_becomes_clear_curator_error() -> None:
    responses = FakeResponses(error=RuntimeError("provider unavailable"))

    with pytest.raises(CuratorError, match="OpenAI curation request failed"):
        curate_research_run(
            one_category_run(make_item("Release")),
            configured_app(),
            client=FakeClient(responses),
        )


def test_missing_configuration_fails_before_request() -> None:
    responses = FakeResponses(error=AssertionError("must not be called"))

    with pytest.raises(CuratorError, match="OPENAI_API_KEY, OPENAI_MODEL"):
        curate_research_run(
            one_category_run(make_item("Release")),
            AppConfig(),
            client=FakeClient(responses),
        )

    assert responses.calls == []


def test_missing_structured_output_fails_clearly() -> None:
    responses = FakeResponses(output_parsed={})

    with pytest.raises(CuratorError, match="Invalid structured curation response"):
        curate_research_run(
            one_category_run(make_item("Release")),
            configured_app(),
            client=FakeClient(responses),
        )
