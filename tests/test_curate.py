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
    FactSupport,
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


def test_normalized_title_legacy_duplicates_ignore_source_quantity() -> None:
    first = make_item("Example Release!", source_urls=("https://a.example",))
    second = make_item(
        "  example release  ",
        source_urls=("https://b.example", "https://c.example"),
    )

    result, client = curate_with(
        one_category_run(first, second),
        assessment("candidate_001"),
    )

    assert len(client.responses.calls) == 1
    assert "candidate_002" not in client.responses.calls[0]["input"]
    assert result[0].item is first


def test_legacy_shared_url_without_guarded_title_reaches_semantic_assessment() -> None:
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
        assessment("candidate_001"),
        assessment("candidate_002"),
    )

    assert [item.item.title for item in result] == [first.title, second.title]


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


def test_exact_duplicate_tie_break_ignores_prose_length() -> None:
    shorter = make_item("Same event", technical_details=["Short."])
    richer = make_item(
        "same event",
        technical_details=["A much more detailed technical explanation."],
    )

    result, _ = curate_with(
        one_category_run(shorter, richer),
        assessment("candidate_001"),
    )

    assert result[0].item is shorter


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


def supported_source(
    url: str,
    *,
    source_type: str = "official",
    summary: bool = True,
    indices: tuple[int, ...] = (0,),
    benchmark: bool = False,
    roles: tuple[str, ...] = ("event", "event_date", "technical"),
) -> Source:
    return Source(
        title="Explicit evidence",
        url=url,
        source_type=source_type,
        evidence_roles=list(roles),
        fact_support=FactSupport(
            summary=summary,
            technical_detail_indices=list(indices),
            benchmark=benchmark,
        ),
    )


def anchored_item(title: str, url: str, **kwargs: Any) -> NewsItem:
    return make_item(title, **kwargs).model_copy(
        update={"sources": [supported_source(url)]}
    )


def prepared(*items: NewsItem) -> list:
    # Preparation flattens source order, independent of category grouping.
    run = make_run(*((item.category, [item]) for item in items))
    return curate_module._prepare_candidates(run)


@pytest.mark.parametrize("source_type", ["official", "paper", "github", "university"])
def test_primary_anchor_collapses_across_category_and_organization(
    source_type: str,
) -> None:
    url = "https://example.com/qualcomm-amazon"
    first = anchored_item(
        "Qualcomm and Amazon announcement", url,
        organization="Qualcomm Technologies and Amazon",
    )
    second = anchored_item(
        "New Qualcomm AWS collaboration", url,
        category="GPU / semiconductor / AI infrastructure",
        organization="Qualcomm Technologies and Amazon Web Services",
    )
    for item in (first, second):
        item.sources[0].source_type = source_type.upper()

    candidates = prepared(first, second)

    assert [candidate.candidate_id for candidate in candidates] == ["candidate_001"]
    assert candidates[0].item is first


@pytest.mark.parametrize(
    ("left_url", "right_url", "collapse"),
    [
        ("HTTPS://EXAMPLE.com/Release/", "https://example.com/Release#event", True),
        ("https://example.com/Release///", "https://example.com/Release", True),
        (
            "https://example.com/Release?a=X#one",
            "https://EXAMPLE.com/Release?a=X", True,
        ),
        ("https://example.com/Release", "https://example.com/release", False),
        ("https://example.com/release?a=X", "https://example.com/release?a=x", False),
        ("https://example.com/release?a=1", "https://example.com/release?a=2", False),
        ("https://example.com/release?a=1", "https://example.com/release", False),
        ("http://example.com/release", "https://example.com/release", False),
        ("https://www.example.com/release", "https://example.com/release", False),
        ("https://example.com/%61", "https://example.com/a", False),
    ],
)
def test_anchor_reuses_existing_url_normalization(
    left_url: str, right_url: str, collapse: bool,
) -> None:
    from ai_weekly_agent.research import normalize_source_url

    first = anchored_item("First headline", left_url)
    second = anchored_item("Second headline", right_url, category="AI research")

    equivalent = normalize_source_url(left_url) == normalize_source_url(right_url)
    assert equivalent == collapse
    assert len(prepared(first, second)) == (1 if collapse else 2)


@pytest.mark.parametrize(
    ("left_date", "right_date"),
    [
        (date(2026, 9, 1), date(2026, 9, 2)),
        (None, date(2026, 9, 2)),
        (date(2026, 9, 2), None),
        (None, None),
    ],
)
def test_anchor_requires_same_known_date(
    left_date: date | None, right_date: date | None,
) -> None:
    first = anchored_item(
        "First headline", "https://example.com/event", published_date=left_date,
    )
    second = anchored_item(
        "Second headline", "https://example.com/event", published_date=right_date,
    )

    assert len(prepared(first, second)) == 2


@pytest.mark.parametrize(
    "source",
    [
        supported_source("https://example.com/shared", source_type="secondary"),
        supported_source("https://example.com/shared", source_type="benchmark"),
        supported_source("https://example.com/shared", source_type="unknown"),
        supported_source(
            "https://example.com/shared", summary=False,
            indices=(), roles=("background",),
        ),
        supported_source("https://example.com/shared", summary=False),
        supported_source("https://example.com/shared", roles=("technical",)),
        supported_source("https://example.com/shared", roles=()),
        make_source("https://example.com/shared"),
    ],
)
def test_nonqualifying_shared_source_does_not_create_anchor(source: Source) -> None:
    first = make_item("First event").model_copy(update={"sources": [source]})
    second = make_item("Second event").model_copy(
        update={"sources": [source.model_copy(deep=True)]}
    )

    assert curate_module._event_anchor(first) is None
    assert len(prepared(first, second)) == 2


def test_first_qualifying_source_is_the_only_anchor() -> None:
    shared = supported_source("https://example.com/shared")
    first = anchored_item("First event", "https://example.com/one")
    second = anchored_item("Second event", "https://example.com/two")
    first.sources.append(shared)
    second.sources.append(shared.model_copy(deep=True))
    first.sources.insert(0, supported_source(
        "https://example.com/context", summary=False, indices=(), roles=("background",),
    ))

    assert curate_module._event_anchor(first) == (
        "https://example.com/one", first.published_date,
    )
    assert len(prepared(first, second)) == 2


@pytest.mark.parametrize("organization", ["EXAMPLE   lab", " example lab "])
def test_title_identity_normalizes_organization_without_aliases(
    organization: str,
) -> None:
    first = make_item(" Example   Release! ")
    second = make_item("example release", organization=organization)

    assert len(prepared(first, second)) == 1


@pytest.mark.parametrize("organization", ["Other Lab", None, "", "   ", "Example Labs"])
def test_generic_same_title_requires_same_nonempty_organization(
    organization: str | None,
) -> None:
    first = make_item("New release", organization=organization)
    second = make_item("New release")

    assert len(prepared(first, second)) == 2


def test_title_identity_does_not_collapse_conflicting_known_dates() -> None:
    first = make_item("Same title", published_date=date(2026, 9, 1))
    second = make_item("Same title", published_date=date(2026, 9, 2))

    assert len(prepared(first, second)) == 2


@pytest.mark.parametrize(
    ("left_date", "right_date", "winner"),
    [(None, None, 0), (None, date(2026, 9, 2), 1), (date(2026, 9, 2), None, 0)],
)
def test_guarded_title_preserves_nonconflicting_unknown_date_compatibility(
    left_date: date | None, right_date: date | None, winner: int,
) -> None:
    items = [
        make_item("Same title", published_date=left_date),
        make_item("Same title", published_date=right_date),
    ]

    candidates = prepared(*items)

    assert len(candidates) == 1
    assert candidates[0].item is items[winner]


@pytest.mark.parametrize("unknown_first", [True, False])
def test_unknown_title_date_cannot_bridge_conflicting_dated_events(
    unknown_first: bool,
) -> None:
    undated = make_item("Same title", published_date=None)
    first = make_item("Same title", published_date=date(2026, 9, 1))
    second = make_item("Same title", published_date=date(2026, 9, 2))
    items = [undated, first, second] if unknown_first else [first, second, undated]

    candidates = prepared(*items)

    assert {candidate.item.published_date for candidate in candidates} >= {
        first.published_date, second.published_date,
    }
    assert len(candidates) == (2 if unknown_first else 3)


def test_complete_new_provenance_outranks_legacy_through_guarded_title() -> None:
    legacy = make_item("Same event")
    explicit = anchored_item("same event", "https://example.com/announcement")

    candidates = prepared(legacy, explicit)

    assert len(candidates) == 1
    assert candidates[0].item is explicit
    assert candidates[0].candidate_id == "candidate_002"


def test_more_unique_primary_support_wins_without_merging_records() -> None:
    first = anchored_item("First headline", "https://example.com/event")
    second = anchored_item("Second headline", "https://example.com/event")
    second.sources.append(supported_source(
        "https://example.com/specification", summary=False, roles=("technical",),
    ))
    second.technical_details = ["One authoritative detail."]
    snapshot = second.model_dump(mode="json")

    candidates = prepared(first, second)

    assert len(candidates) == 1
    assert candidates[0].item is second
    assert candidates[0].item.model_dump(mode="json") == snapshot
    assert candidates[0].item.title != first.title


def test_repeated_equivalent_source_urls_do_not_inflate_evidence_preference() -> None:
    first = anchored_item("First headline", "https://example.com/event")
    second = anchored_item("Second headline", "https://example.com/event")
    second.sources.append(supported_source("https://EXAMPLE.com/event/#fragment"))

    assert curate_module._explicit_evidence_counts(second) == (1, 1)
    assert prepared(first, second)[0].item is first


def test_background_source_count_and_long_prose_do_not_win() -> None:
    first = anchored_item("First headline", "https://example.com/event")
    second = anchored_item("Second headline", "https://example.com/event")
    second.summary = "Long background prose. " * 20
    second.technical_details = ["Verbose technical prose. " * 20]
    second.sources.extend(supported_source(
        f"https://example.com/background-{index}", summary=False,
        indices=(), roles=("background",),
    ) for index in range(10))

    assert curate_module._explicit_evidence_counts(second) == (1, 1)
    assert prepared(first, second)[0].item is first


def test_original_benchmark_evidence_counts_only_as_benchmark_support() -> None:
    first = anchored_item("First headline", "https://example.com/event")
    second = anchored_item("Second headline", "https://example.com/event")
    second.benchmark_information = "Original evaluation reports a qualified result."
    second.sources.append(supported_source(
        "https://example.com/evaluation", source_type="benchmark", summary=False,
        indices=(), benchmark=True, roles=("benchmark",),
    ))

    assert curate_module._explicit_evidence_counts(second) == (1, 2)
    assert curate_module._primary_source_count(second) == 1
    assert prepared(first, second)[0].item is second


@pytest.mark.parametrize("source_type", ["benchmark", "unknown"])
def test_nonprimary_event_label_does_not_inflate_primary_quality(
    source_type: str,
) -> None:
    item = anchored_item("Event", "https://example.com/event")
    item.sources.append(supported_source(
        "https://example.com/extra", source_type=source_type,
    ))

    assert curate_module._explicit_evidence_counts(item) == (1, 1)
    assert curate_module._primary_source_count(item) == 1


def test_secondary_explicit_corroboration_is_relevant_but_not_primary() -> None:
    first = anchored_item("First headline", "https://example.com/event")
    second = anchored_item("Second headline", "https://example.com/event")
    second.sources.append(supported_source(
        "https://example.com/reporting", source_type="secondary",
    ))

    assert curate_module._explicit_evidence_counts(second) == (1, 2)
    assert prepared(first, second)[0].item is second


def test_partial_metadata_does_not_outrank_complete_metadata() -> None:
    complete = anchored_item("Same event", "https://example.com/event")
    partial = anchored_item("Same event", "https://example.com/event")
    partial.sources.append(make_source("https://example.com/legacy-background"))
    partial.sources.append(supported_source("https://example.com/specification"))

    assert prepared(complete, partial)[0].item is complete


def test_arbitrary_shared_urls_never_build_transitive_groups() -> None:
    first = make_item("First event", source_urls=("https://example.com/a",))
    bridge = make_item(
        "Middle event", source_urls=("https://example.com/a", "https://example.com/b"),
    )
    last = make_item("Last event", source_urls=("https://example.com/b",))

    assert [candidate.item for candidate in prepared(first, bridge, last)] == [
        first, bridge, last,
    ]


@pytest.mark.parametrize("reverse_order", [True, False])
def test_anchor_group_is_not_bridged_by_one_members_title(reverse_order: bool) -> None:
    first = anchored_item("First headline", "https://example.com/one")
    bridge = anchored_item("Shared headline", "https://example.com/one")
    last = anchored_item("Shared headline", "https://example.com/two")
    items = [last, bridge, first] if reverse_order else [first, bridge, last]

    candidates = prepared(*items)

    assert len(candidates) == 2
    anchors = {
        curate_module._event_anchor(candidate.item)[0] for candidate in candidates
    }
    assert anchors == {
        "https://example.com/one", "https://example.com/two",
    }


def test_legacy_title_cannot_bridge_different_qualifying_anchors() -> None:
    first = anchored_item("Same title", "https://example.com/one")
    bridge = make_item("Same title")
    last = anchored_item("Same title", "https://example.com/two")

    candidates = prepared(first, bridge, last)

    assert [candidate.item for candidate in candidates] == [first, last]


def test_different_qualifying_anchors_remain_for_semantic_assessment() -> None:
    first = anchored_item("Same title", "https://example.com/one")
    second = anchored_item("Same title", "https://example.com/two")

    result, client = curate_with(
        one_category_run(first, second),
        assessment("candidate_001"),
        assessment("candidate_002", duplicate_of="candidate_001"),
    )

    assert len(client.responses.calls) == 1
    assert '"candidate_id": "candidate_002"' in client.responses.calls[0]["input"]
    assert [item.item for item in result] == [first]


def test_multi_event_announcement_used_only_as_background_is_not_an_identity() -> None:
    first = anchored_item("Launch A", "https://example.com/launch-a")
    second = anchored_item("Launch B", "https://example.com/launch-b")
    background = supported_source(
        "https://example.com/multi-event-announcement", summary=False,
        indices=(), roles=("background",),
    )
    first.sources.insert(0, background)
    second.sources.insert(0, background.model_copy(deep=True))

    assert len(prepared(first, second)) == 2


def test_preparation_is_immutable_repeatable_and_retains_original_id_gaps() -> None:
    rejected = make_item("Outside", published_date=date(2026, 8, 29))
    legacy = make_item("Same title")
    winner = anchored_item("Same title", "https://example.com/event")
    winner.sources.append(supported_source(
        "https://example.com/specification", summary=False, roles=("technical",),
    ))
    other = make_item("Other event")
    run = one_category_run(rejected, legacy, winner, other)
    before = run.model_dump(mode="json")

    first = curate_module._prepare_candidates(run)
    second = curate_module._prepare_candidates(run)

    assert first == second
    assert run.model_dump(mode="json") == before
    assert [candidate.candidate_id for candidate in first] == [
        "candidate_003", "candidate_004",
    ]
    assert first[0].item is winner
    assert first[0].item.sources == winner.sources


def test_semantic_primary_tie_does_not_treat_benchmark_as_event_primary() -> None:
    benchmark = make_item("Evaluation only", source_type="benchmark")
    official = make_item("Primary event", source_type="official")

    result, client = curate_with(
        one_category_run(benchmark, official),
        assessment("candidate_001", duplicate_of="candidate_002"),
        assessment("candidate_002"),
    )

    assert len(client.responses.calls) == 1
    assert result[0].item is official


def test_anchor_requires_role_metadata_even_with_explicit_summary_support() -> None:
    first = anchored_item("First event", "https://example.com/event")
    second = anchored_item("Second event", "https://example.com/event")
    first.sources[0].evidence_roles = None
    second.sources[0].evidence_roles = None

    assert curate_module._event_anchor(first) is None
    assert len(prepared(first, second)) == 2


def test_primary_support_precedes_many_secondary_corroborating_sources() -> None:
    primary = anchored_item("First event", "https://example.com/event")
    primary.sources.append(supported_source(
        "https://example.com/specification", summary=False, roles=("technical",),
    ))
    secondary = anchored_item("Second event", "https://example.com/event")
    secondary.sources.extend(supported_source(
        f"https://example.com/secondary-{index}", source_type="secondary",
    ) for index in range(5))

    assert curate_module._explicit_evidence_counts(primary) == (2, 2)
    assert curate_module._explicit_evidence_counts(secondary) == (1, 6)
    assert prepared(primary, secondary)[0].item is primary


def test_known_date_tie_break_with_complete_metadata_on_both_records() -> None:
    undated = anchored_item(
        "Same event", "https://example.com/event", published_date=None,
    )
    dated = anchored_item("Same event", "https://example.com/event")

    assert prepared(undated, dated)[0].item is dated


def test_removed_exact_duplicate_id_is_still_an_unknown_assessment_id() -> None:
    first = anchored_item("First event", "https://example.com/event")
    stronger = anchored_item("Second event", "https://example.com/event")
    stronger.sources.append(supported_source("https://example.com/specification"))
    client = client_for(assessment("candidate_001"), assessment("candidate_002"))

    with pytest.raises(CuratorError, match="unknown candidate ID: candidate_001"):
        curate_research_run(
            one_category_run(first, stronger), configured_app(), client=client,
        )

    assert len(client.responses.calls) == 1


def test_multi_member_anchor_group_remains_separate_from_legacy_title_match() -> None:
    first = anchored_item("Same title", "https://example.com/event")
    second = anchored_item("Same title", "https://example.com/event")
    legacy = make_item("Same title")

    candidates = prepared(legacy, first, second)

    assert [candidate.item for candidate in candidates] == [legacy, first]


def test_date_role_can_contribute_primary_support_without_summary_or_details() -> None:
    item = anchored_item("Event", "https://example.com/event")
    item.sources.append(supported_source(
        "https://example.com/dated-release", summary=False, indices=(),
        roles=("event_date",),
    ))

    assert curate_module._explicit_evidence_counts(item) == (2, 2)
    assert curate_module._primary_source_count(item) == 2


def test_background_primary_source_does_not_improve_semantic_event_quality() -> None:
    item = anchored_item("Event", "https://example.com/event")
    item.sources.append(supported_source(
        "https://example.com/context", summary=False, indices=(),
        roles=("background",),
    ))

    assert curate_module._primary_source_count(item) == 1
