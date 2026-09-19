import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_weekly_agent import research as research_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.dates import raw_research_filename
from ai_weekly_agent.models import CategoryResearchResult, DateRange, ResearchRun
from ai_weekly_agent.research import (
    RESEARCH_CATEGORIES,
    ResearchError,
    research_all_categories,
    research_category,
    save_research_run,
)
from ai_weekly_agent.telemetry import TelemetryRecorder, observe_openai_client
from ai_weekly_agent.verify import verify_research_run


DATE_RANGE = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
CATEGORY = RESEARCH_CATEGORIES[0]
VALID_URL = "https://example.com/release"


def configured_app() -> AppConfig:
    return AppConfig(
        openai_api_key="test-key-not-a-real-credential",
        openai_model="test-model",
    )


def candidate(
    *,
    title: str = "Example release",
    category: str = CATEGORY,
    published_date: str | None = "2026-09-02",
    benchmark_information: str | None = None,
    source_urls: tuple[str, ...] = (VALID_URL,),
) -> dict[str, Any]:
    return {
        "title": title,
        "category": category,
        "organization": "Example Lab",
        "published_date": published_date,
        "summary": "Example Lab released a documented system.",
        "technical_details": ["A source-supported technical detail."],
        "benchmark_information": benchmark_information,
        "sources": [
            {
                "title": f"Source {index}",
                "url": url,
                "source_type": "official",
            }
            for index, url in enumerate(source_urls, start=1)
        ],
    }


def response_for(
    result: dict[str, Any] | CategoryResearchResult,
    *,
    web_urls: tuple[str, ...] = (VALID_URL,),
) -> dict[str, Any]:
    return {
        "output_parsed": result,
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "sources": [
                        {"type": "url", "url": url} for url in web_urls
                    ],
                },
            }
        ],
    }


class FakeResponses:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses
        self.marker = object()


def client_for(
    result: dict[str, Any] | CategoryResearchResult,
    *,
    web_urls: tuple[str, ...] = (VALID_URL,),
) -> FakeClient:
    return FakeClient(FakeResponses(response_for(result, web_urls=web_urls)))


def single_result(*items: dict[str, Any]) -> dict[str, Any]:
    return {"category": CATEGORY, "items": list(items)}


@pytest.fixture
def research_prompt() -> str:
    """Capture the rendered prompt at the fake API boundary."""
    client = client_for(single_result())
    research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)
    return " ".join(client.responses.calls[0]["input"].split())


def test_research_uses_configured_model() -> None:
    client = client_for(single_result())

    research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)

    assert client.responses.calls[0]["model"] == "test-model"


def test_research_fallback_uses_centralized_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for(single_result())
    config = configured_app()
    factory_calls: list[AppConfig] = []

    def fake_factory(received_config: AppConfig) -> FakeClient:
        factory_calls.append(received_config)
        return client

    monkeypatch.setattr(research_module, "create_openai_client", fake_factory)

    research_category(DATE_RANGE, CATEGORY, config)

    assert factory_calls == [config]
    assert len(client.responses.calls) == 1


def test_research_enables_web_search_and_source_metadata() -> None:
    client = client_for(single_result())

    research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)

    call = client.responses.calls[0]
    assert call["tools"] == [{"type": "web_search"}]
    assert call["include"] == ["web_search_call.action.sources"]


def test_research_limits_built_in_tool_calls_to_four() -> None:
    client = client_for(single_result())

    research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)

    assert len(client.responses.calls) == 1
    assert client.responses.calls[0]["max_tool_calls"] == 4


def test_research_prompt_contains_category_and_date_range() -> None:
    client = client_for(single_result())

    research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)

    prompt = client.responses.calls[0]["input"]
    assert f"Research category: {CATEGORY}" in prompt
    assert "2026-08-30 through 2026-09-05" in prompt


def test_research_prompt_requests_direct_primary_sources(
    research_prompt: str,
) -> None:
    assert "prefer a direct canonical primary-source page" in research_prompt
    assert "direct official company or organization announcement" in research_prompt
    assert "direct documentation or release page" in research_prompt
    assert "When a specific page exists, avoid using" in research_prompt
    assert "generic newsroom index" in research_prompt
    assert "URL-shortener/tracking URL as the main source" in research_prompt
    assert "must not replace a primary source when one exists" in research_prompt


def test_research_prompt_bounds_discovery_depth(research_prompt: str) -> None:
    assert "not an exhaustive deep-research task" in research_prompt
    assert "Avoid exhaustive searching" in research_prompt
    assert "Stop researching when you have enough evidence" in research_prompt
    assert "approximately 0-5 strong candidate stories" in research_prompt
    assert "Prioritize quality over coverage" in research_prompt


def test_research_prompt_requests_release_time_evidence(
    research_prompt: str,
) -> None:
    assert "prefer dated/version-specific evidence" in research_prompt
    assert "capabilities available at launch" in research_prompt
    assert "benchmark results announced at launch" in research_prompt
    for evidence_type in (
        "direct launch announcement",
        "dated release notes",
        "versioned documentation",
        "dated model card",
        "paper/arXiv version",
        "dated GitHub release",
        "dated university/lab publication",
    ):
        assert evidence_type in research_prompt


def test_research_prompt_limits_mutable_pages_to_current_context(
    research_prompt: str,
) -> None:
    assert (
        "A mutable generic product page may be used for current background context"
    ) in research_prompt
    assert (
        "must not be the sole evidence for a historical launch-time claim "
        "when dated release evidence should exist"
    ) in research_prompt
    assert (
        "Do not treat a later page update or current availability as proof "
        "of what was available at launch"
    ) in research_prompt


def test_research_prompt_allows_zero_results(research_prompt: str) -> None:
    assert "Return zero items when nothing important occurred" in research_prompt
    assert "do not force a minimum or exactly five items" in research_prompt


def test_research_prompt_separates_performance_claims(
    research_prompt: str,
) -> None:
    assert (
        "Use `technical_details` for source-supported architecture"
    ) in research_prompt
    assert (
        "Put all quantitative performance claims in `benchmark_information`, "
        "not in `technical_details`"
    ) in research_prompt
    assert "measured latency, measured throughput" in research_prompt
    assert "fewer tool calls or tokens for the same workload" in research_prompt
    assert (
        "If reliable benchmark/performance evidence is unavailable, set "
        "`benchmark_information` to null and omit those claims"
    ) in research_prompt
    assert "Never invent or infer benchmark numbers" in research_prompt


def test_research_prompt_requests_source_evidence_roles(
    research_prompt: str,
) -> None:
    assert "Populate `evidence_roles` for every source" in research_prompt
    assert "source may have more than one role" in research_prompt
    for role in (
        "event",
        "event_date",
        "technical",
        "benchmark",
        "background",
    ):
        assert f"`{role}`" in research_prompt
    assert '["event", "event_date", "technical"]' in research_prompt
    assert '["benchmark", "technical"]' in research_prompt
    assert '["background"]' in research_prompt
    assert "Do not assign a role unless that specific source supports it" in (
        research_prompt
    )


def test_structured_output_becomes_category_result() -> None:
    client = client_for(single_result(candidate()))

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert isinstance(result, CategoryResearchResult)
    assert result.items[0].title == "Example release"
    assert client.responses.calls[0]["text_format"] is CategoryResearchResult


def test_valid_web_search_source_remains_and_is_normalized() -> None:
    source_url = "https://EXAMPLE.com/release/#details"
    client = client_for(
        single_result(candidate(source_urls=(source_url,))),
        web_urls=(VALID_URL,),
    )

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert result.items[0].sources[0].url == VALID_URL


@pytest.mark.parametrize("as_attributes", [False, True], ids=["dict", "object"])
@pytest.mark.parametrize("action_type", ["search", "open_page", "find_in_page"])
@pytest.mark.parametrize(
    ("status", "expected_urls"),
    [
        ("completed", [VALID_URL]),
        ("searching", []),
        ("in_progress", []),
        ("failed", []),
        pytest.param(None, [], id="missing-status"),
    ],
)
def test_only_completed_tool_calls_support_item_sources(
    as_attributes: bool,
    action_type: str,
    status: str | None,
    expected_urls: list[str],
) -> None:
    action: dict[str, Any] = {"type": action_type}
    if action_type == "search":
        source = {"type": "url", "url": VALID_URL}
        action["sources"] = [
            SimpleNamespace(**source) if as_attributes else source
        ]
    else:
        action["url"] = VALID_URL
        if action_type == "find_in_page":
            action["pattern"] = "release"

    call: dict[str, Any] = {
        "type": "web_search_call",
        "action": SimpleNamespace(**action) if as_attributes else action,
    }
    if status is not None:
        call["status"] = status
    response = response_for(single_result(candidate()))
    response["output"] = [SimpleNamespace(**call) if as_attributes else call]
    client = FakeClient(FakeResponses(response))

    result = research_category(
        DATE_RANGE, CATEGORY, configured_app(), client=client
    )

    assert [
        source.url for item in result.items for source in item.sources
    ] == expected_urls
    assert len(result.items) == (1 if expected_urls else 0)


def test_unfinished_sources_are_removed_without_affecting_valid_stories() -> None:
    unfinished_url = "https://example.com/unconfirmed-release"
    valid = candidate(title="Completed-source story")
    mixed = candidate(
        title="Mixed-source story", source_urls=(VALID_URL, unfinished_url)
    )
    unfinished = candidate(
        title="Unfinished-source story", source_urls=(unfinished_url,)
    )
    response = response_for(single_result(valid, mixed, unfinished))
    response["output"].append({
        "type": "web_search_call",
        "status": "searching",
        "action": {"type": "open_page", "url": unfinished_url},
    })
    client = FakeClient(FakeResponses(response))

    result = research_category(
        DATE_RANGE, CATEGORY, configured_app(), client=client
    )

    assert [item.title for item in result.items] == [valid["title"], mixed["title"]]
    assert [
        [source.url for source in item.sources] for item in result.items
    ] == [[VALID_URL], [VALID_URL]]


def test_unsupported_source_url_is_removed() -> None:
    unsupported = "https://unsupported.example/story"
    client = client_for(
        single_result(candidate(source_urls=(VALID_URL, unsupported))),
    )

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert [source.url for source in result.items[0].sources] == [VALID_URL]


def test_item_without_supported_sources_is_rejected() -> None:
    client = client_for(
        single_result(candidate(source_urls=("https://unsupported.example",))),
    )

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert result.items == []


def test_out_of_range_candidate_is_rejected() -> None:
    client = client_for(
        single_result(candidate(published_date="2026-08-29")),
    )

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert result.items == []


def test_unknown_date_is_retained_without_inference() -> None:
    client = client_for(single_result(candidate(published_date=None)))

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert len(result.items) == 1
    assert result.items[0].published_date is None


def test_missing_benchmark_information_is_accepted() -> None:
    client = client_for(
        single_result(candidate(benchmark_information=None)),
    )

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert result.items[0].benchmark_information is None


def test_empty_category_result_is_accepted() -> None:
    client = client_for(single_result(), web_urls=())

    result = research_category(
        DATE_RANGE,
        CATEGORY,
        configured_app(),
        client=client,
    )

    assert result == CategoryResearchResult(category=CATEGORY, items=[])


def test_missing_configuration_fails_before_client_request() -> None:
    responses = FakeResponses(error=AssertionError("must not be called"))
    client = FakeClient(responses)

    with pytest.raises(ResearchError, match="OPENAI_API_KEY, OPENAI_MODEL"):
        research_category(DATE_RANGE, CATEGORY, AppConfig(), client=client)

    assert responses.calls == []


def test_openai_exception_becomes_clear_research_error() -> None:
    client = FakeClient(FakeResponses(error=RuntimeError("provider unavailable")))

    with pytest.raises(
        ResearchError,
        match=f"OpenAI research request failed for category: {CATEGORY}",
    ):
        research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)


class CategoryResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        prompt = kwargs["input"]
        category = next(
            category
            for category in RESEARCH_CATEGORIES
            if f"Research category: {category}" in prompt
        )
        return response_for({"category": category, "items": []}, web_urls=())


def test_all_categories_are_researched_in_deterministic_order() -> None:
    responses = CategoryResponses()

    research_all_categories(
        DATE_RANGE,
        configured_app(),
        client=FakeClient(responses),
    )

    requested_categories = [
        next(
            category
            for category in RESEARCH_CATEGORIES
            if f"Research category: {category}" in call["input"]
        )
        for call in responses.calls
    ]
    assert requested_categories == list(RESEARCH_CATEGORIES)


def test_all_categories_are_assembled_into_research_run() -> None:
    responses = CategoryResponses()

    run = research_all_categories(
        DATE_RANGE,
        configured_app(),
        client=FakeClient(responses),
    )

    assert isinstance(run, ResearchRun)
    assert run.date_range == DATE_RANGE
    assert [result.category for result in run.categories] == list(
        RESEARCH_CATEGORIES
    )


def test_all_categories_receive_explicit_ordered_telemetry_context() -> None:
    base_client = FakeClient(CategoryResponses())
    recorder = TelemetryRecorder()
    observed_clients: list[object] = []

    def client_for_category(category: str) -> object:
        observed = observe_openai_client(
            base_client,
            recorder,
            "research",
            research_category=category,
        )
        observed_clients.append(observed)
        return observed

    research_all_categories(
        DATE_RANGE,
        configured_app(),
        client_for_category=client_for_category,
    )

    assert [record.research_category for record in recorder.records] == list(
        RESEARCH_CATEGORIES
    )
    assert all(client.marker is base_client.marker for client in observed_clients)
    assert all(
        "research_category" not in call
        for call in base_client.responses.calls
    )


def test_failing_category_is_recorded_without_an_extra_logical_call() -> None:
    failed_index = 2

    class FailingCategoryResponses:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def parse(self, **kwargs: Any) -> dict[str, Any]:
            index = len(self.calls)
            self.calls.append(kwargs)
            if index == failed_index:
                raise RuntimeError("provider failed")
            category = RESEARCH_CATEGORIES[index]
            return response_for(
                {"category": category, "items": []},
                web_urls=(),
            )

    responses = FailingCategoryResponses()
    base_client = FakeClient(responses)
    recorder = TelemetryRecorder()

    def client_for_category(category: str) -> object:
        return observe_openai_client(
            base_client,
            recorder,
            "research",
            research_category=category,
        )

    with pytest.raises(
        ResearchError,
        match=f"OpenAI research request failed for category: "
        f"{RESEARCH_CATEGORIES[failed_index]}",
    ):
        research_all_categories(
            DATE_RANGE,
            configured_app(),
            client_for_category=client_for_category,
        )

    assert len(responses.calls) == failed_index + 1
    assert len(recorder.records) == failed_index + 1
    assert [record.research_category for record in recorder.records] == list(
        RESEARCH_CATEGORIES[: failed_index + 1]
    )
    assert recorder.records[-1].status == "failed"


def empty_research_run() -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            CategoryResearchResult(category=category, items=[])
            for category in RESEARCH_CATEGORIES
        ],
    )


def test_raw_research_is_saved_with_expected_filename_and_json(
    tmp_path: Path,
) -> None:
    run = empty_research_run()

    output_path = save_research_run(run, output_dir=tmp_path)

    assert output_path.name == raw_research_filename(DATE_RANGE)
    assert json.loads(output_path.read_text(encoding="utf-8")) == run.model_dump(
        mode="json"
    )


def test_failed_atomic_replace_does_not_corrupt_existing_raw_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / raw_research_filename(DATE_RANGE)
    target.write_text("existing valid research\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(research_module.os, "replace", fail_replace)

    with pytest.raises(ResearchError, match="Could not save raw research"):
        save_research_run(empty_research_run(), output_dir=tmp_path)

    assert target.read_text(encoding="utf-8") == "existing valid research\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_research_prompt_requests_complete_fact_support(research_prompt: str) -> None:
    for text in (
        "Include non-null `fact_support` for every retained source",
        "this item's factual event summary",
        "distinct zero-based positions",
        "0 is the first detail",
        "true requires an `event` role",
        "each index requires a `technical` role",
        "true requires a `benchmark` role",
        "Background-only sources use summary=false, benchmark=false, and no indices",
    ):
        assert text in research_prompt


def test_research_prompt_requests_per_fact_primary_or_original_evidence(
    research_prompt: str,
) -> None:
    for text in (
        "summary and every supplied technical detail need explicit retained",
        "A known `published_date` also needs such a source with `event_date` evidence",
        "Place the direct primary/original event announcement first",
        "Omit unsupported technical details",
        "otherwise leave it null",
        "Reserve `benchmark` for an original evaluation report",
        "cannot substitute for primary event/date or product-specification evidence",
        "Secondary reporting may corroborate but must not be the only evidence",
        "do not collect unnecessary extra sources",
        "do not independently prove webpage semantics",
    ):
        assert text in research_prompt


def fact_support_payload(
    *, summary: bool = True, indices: list[int] | None = None,
    benchmark: bool = False,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "technical_detail_indices": [0] if indices is None else indices,
        "benchmark": benchmark,
    }


def complete_run_with(result: CategoryResearchResult) -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            result
            if category == CATEGORY
            else CategoryResearchResult(category=category)
            for category in RESEARCH_CATEGORIES
        ],
    )


def test_research_preserves_fact_support_through_normalization_and_raw_save(
    tmp_path: Path,
) -> None:
    item = candidate(source_urls=("https://EXAMPLE.com/release/#launch",))
    source = item["sources"][0]
    source["evidence_roles"] = ["event", "event_date", "technical"]
    source["fact_support"] = fact_support_payload()
    client = client_for(single_result(item))

    result = research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)
    run = complete_run_with(result)
    saved_path = save_research_run(run, output_dir=tmp_path)
    restored = ResearchRun.model_validate_json(saved_path.read_text(encoding="utf-8"))

    assert restored == run
    assert result.items[0].sources[0].url == VALID_URL
    support = result.items[0].sources[0].fact_support
    assert support is not None
    assert support.model_dump() == fact_support_payload()
    assert verify_research_run(run, require_provenance=True).rejected_item_ids == []
    assert len(client.responses.calls) == 1


@pytest.mark.parametrize(
    "discarded_kind",
    ["searching", "in_progress", "failed", "unsupported", "invalid", "duplicate"],
)
def test_discarded_research_source_cannot_supply_any_fact_coverage(
    discarded_kind: str,
) -> None:
    removed_url = {
        "invalid": "not-a-url",
        "duplicate": "https://EXAMPLE.com/release/#launch",
    }.get(discarded_kind, "https://example.com/discarded")
    item = candidate(
        benchmark_information="Company-reported throughput was 100 tokens/s.",
        source_urls=(VALID_URL, removed_url),
    )
    item["sources"][0].update(
        evidence_roles=["event_date"],
        fact_support=fact_support_payload(summary=False, indices=[]),
    )
    item["sources"][1].update(
        evidence_roles=["event", "event_date", "technical", "benchmark"],
        fact_support=fact_support_payload(benchmark=True),
    )
    response = response_for(single_result(item))
    if discarded_kind in {"searching", "in_progress", "failed"}:
        response["output"].append(
            {
                "type": "web_search_call", "status": discarded_kind,
                "action": {"sources": [{"url": removed_url}]},
            }
        )
    client = FakeClient(FakeResponses(response))

    result = research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)
    verification = verify_research_run(
        complete_run_with(result), require_provenance=True
    )

    assert len(result.items) == 1
    assert len(result.items[0].sources) == 1
    assert result.items[0].sources[0].fact_support.summary is False
    assert verification.rejected_item_ids == ["category_01:item_001"]
    assert {
        "event_evidence_missing", "technical_evidence_missing",
        "benchmark_evidence_missing",
    } <= {finding.code for finding in verification.findings}
    assert len(client.responses.calls) == 1


def test_malformed_fact_support_fails_research_without_retry() -> None:
    item = candidate()
    item["sources"][0]["fact_support"] = fact_support_payload(indices=[True])
    client = client_for(single_result(item))

    with pytest.raises(research_module.ResearchError, match="Invalid structured"):
        research_category(DATE_RANGE, CATEGORY, configured_app(), client=client)

    assert len(client.responses.calls) == 1
