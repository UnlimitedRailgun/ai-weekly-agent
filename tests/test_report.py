from datetime import date
from pathlib import Path
from typing import Any

import pytest

import ai_weekly_agent.report as report_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.models import CuratedItem, DateRange, NewsItem, Source
from ai_weekly_agent.report import (
    NO_BENCHMARK_INFORMATION,
    ConceptExplanation,
    ReportContent,
    ReportError,
    StoryExplanation,
    generate_report,
    render_markdown,
    save_report,
)


DATE_RANGE = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
MODEL = "test-model"
_UNSET = object()


def configured_app() -> AppConfig:
    return AppConfig(
        openai_api_key="test-key-not-a-real-credential",
        openai_model=MODEL,
    )


def make_source(
    title: str = "Official announcement",
    url: str = "https://example.com/announcement",
    source_type: str = "official",
) -> Source:
    return Source(title=title, url=url, source_type=source_type)


def make_curated_item(
    title: str = "Example release",
    *,
    category: str = "AI model releases",
    organization: str | None = "Example Lab",
    published_date: date | None = date(2026, 9, 2),
    summary: str | None = None,
    technical_details: list[str] | None = None,
    benchmark_information: str | None = None,
    sources: list[Source] | None = None,
    final_score: float = 4.25,
) -> CuratedItem:
    return CuratedItem(
        item=NewsItem(
            title=title,
            category=category,
            organization=organization,
            published_date=published_date,
            summary=summary or f"Researched summary for {title}.",
            technical_details=(
                technical_details
                if technical_details is not None
                else [f"Technical detail for {title}."]
            ),
            benchmark_information=benchmark_information,
            sources=sources or [make_source()],
        ),
        final_score=final_score,
    )


def explanation(
    story_id: str,
    *,
    what_it_is: str | None = None,
    why_it_matters: str | None = None,
    student_takeaway: str | None = None,
) -> dict[str, Any]:
    return {
        "story_id": story_id,
        "what_it_is": what_it_is or f"What it is for {story_id}.",
        "why_it_matters": why_it_matters or f"Why it matters for {story_id}.",
        "student_takeaway": (
            student_takeaway or f"Student takeaway for {story_id}."
        ),
    }


def report_payload(
    *explanations: dict[str, Any],
    concepts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "story_explanations": list(explanations),
        "concepts": concepts if concepts is not None else [],
    }


class FakeResponses:
    def __init__(
        self,
        output_parsed: object = _UNSET,
        *,
        error: Exception | None = None,
    ) -> None:
        self.output_parsed = output_parsed
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        parsed = (
            report_payload(explanation("story_001"))
            if self.output_parsed is _UNSET
            else self.output_parsed
        )
        return {"output_parsed": parsed}


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def generate_with(
    items: list[CuratedItem],
    payload: object,
) -> tuple[str, FakeClient]:
    client = FakeClient(FakeResponses(payload))
    markdown = generate_report(
        DATE_RANGE,
        items,
        configured_app(),
        client=client,
    )
    return markdown, client


def parsed_content(
    *explanations: dict[str, Any],
    concepts: list[dict[str, Any]] | None = None,
) -> ReportContent:
    return ReportContent.model_validate(
        report_payload(
            *explanations,
            concepts=concepts,
        )
    )


def test_empty_curated_list_generates_markdown_without_api_call() -> None:
    responses = FakeResponses(error=AssertionError("must not be called"))

    markdown = generate_report(
        DATE_RANGE,
        [],
        AppConfig(),
        client=FakeClient(responses),
    )

    assert "No stories passed the curation threshold" in markdown
    assert responses.calls == []


def test_empty_report_includes_date_range() -> None:
    markdown = render_markdown(DATE_RANGE, [])

    assert "**Week:** 2026-08-30 — 2026-09-05" in markdown
    assert "## This Week at a Glance" in markdown
    assert "## Major Updates" not in markdown


def test_configured_openai_model_is_used() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert client.responses.calls[0]["model"] == MODEL
    assert client.responses.calls[0]["text_format"] is ReportContent


def test_report_fallback_uses_centralized_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        FakeResponses(report_payload(explanation("story_001")))
    )
    config = configured_app()
    factory_calls: list[AppConfig] = []

    def fake_factory(received_config: AppConfig) -> FakeClient:
        factory_calls.append(received_config)
        return client

    monkeypatch.setattr(report_module, "create_openai_client", fake_factory)

    markdown = generate_report(
        DATE_RANGE,
        [make_curated_item()],
        config,
    )

    assert factory_calls == [config]
    assert len(client.responses.calls) == 1
    assert markdown.startswith("# AI & Computer Engineering Weekly")


def test_multiple_stories_use_exactly_one_llm_request() -> None:
    items = [make_curated_item("First"), make_curated_item("Second")]

    _, client = generate_with(
        items,
        report_payload(explanation("story_001"), explanation("story_002")),
    )

    assert len(client.responses.calls) == 1


def test_one_story_uses_the_same_llm_flow() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert len(client.responses.calls) == 1


def test_story_explanation_contains_only_interpretive_fields() -> None:
    assert set(StoryExplanation.model_fields) == {
        "story_id",
        "what_it_is",
        "why_it_matters",
        "student_takeaway",
    }


def test_report_content_contains_no_model_written_weekly_summary() -> None:
    assert set(ReportContent.model_fields) == {
        "story_explanations",
        "concepts",
    }

    stale = report_payload(explanation("story_001"))
    stale["week_summary"] = ["A model-written factual recap."]

    with pytest.raises(ReportError, match="Invalid structured report response"):
        generate_with([make_curated_item()], stale)


def test_v02_date_restatement_field_is_forbidden() -> None:
    item = make_curated_item(published_date=date(2026, 8, 31))
    stale = explanation("story_001")
    stale["what_happened"] = "On September 1, 2026, the product launched."

    with pytest.raises(ReportError, match="Invalid structured report response"):
        generate_with([item], report_payload(stale))


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "organization",
        "published_date",
        "category",
        "sources",
        "benchmark_explanation",
        "technical_explanation",
    ],
)
def test_stale_authoritative_response_fields_are_forbidden(field: str) -> None:
    stale = explanation("story_001")
    stale[field] = "model-owned value"

    with pytest.raises(ReportError, match="Invalid structured report response"):
        generate_with([make_curated_item()], report_payload(stale))


def test_report_request_has_no_tools_or_web_search() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    call = client.responses.calls[0]
    assert "tools" not in call
    assert "tool_choice" not in call
    assert "web_search" not in call["input"]
    assert "Do not browse, search, call tools" in call["input"]
    assert "Do not restate" in call["input"]


def test_report_prompt_contains_context_needed_for_explanation() -> None:
    item = make_curated_item(
        "Specific accelerator",
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[make_source("Specific source", source_type="benchmark")],
    )

    _, client = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    prompt = client.responses.calls[0]["input"]
    assert "Specific accelerator" in prompt
    assert "Researched summary for Specific accelerator." in prompt
    assert "Technical detail for Specific accelerator." in prompt


def test_report_prompt_omits_metadata_the_model_must_not_restate() -> None:
    item = make_curated_item(
        "Specific accelerator",
        organization="Specific Lab",
        published_date=date(2026, 8, 31),
        benchmark_information="Company-reported latency was 12 ms.",
        sources=[make_source("Specific source", source_type="benchmark")],
    )

    _, client = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    prompt = client.responses.calls[0]["input"]
    assert '"organization"' not in prompt
    assert '"published_date"' not in prompt
    assert '"curation_score"' not in prompt
    assert '"benchmark_information"' not in prompt
    assert '"source_context"' not in prompt
    assert "Specific Lab" not in prompt
    assert "Company-reported latency was 12 ms." not in prompt
    assert "Specific source" not in prompt


def test_source_urls_are_not_sent_to_the_model() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert "https://example.com/announcement" not in client.responses.calls[0][
        "input"
    ]


def test_stable_story_ids_follow_curated_item_order() -> None:
    items = [make_curated_item("First"), make_curated_item("Second")]

    _, client = generate_with(
        items,
        report_payload(explanation("story_001"), explanation("story_002")),
    )

    prompt = client.responses.calls[0]["input"]
    assert prompt.index('"story_id": "story_001"') < prompt.index(
        '"story_id": "story_002"'
    )
    assert prompt.index('"title": "First"') < prompt.index(
        '"title": "Second"'
    )


def test_structured_explanations_map_by_id_but_render_in_story_order() -> None:
    first = make_curated_item("First")
    second = make_curated_item("Second")

    markdown, _ = generate_with(
        [first, second],
        report_payload(
            explanation("story_002", what_it_is="Second explanation."),
            explanation("story_001", what_it_is="First explanation."),
        ),
    )

    assert markdown.index("### 1. First") < markdown.index("### 2. Second")
    assert markdown.index("First explanation.") < markdown.index(
        "Second explanation."
    )


def test_unknown_story_id_fails() -> None:
    with pytest.raises(ReportError, match="unknown story ID: story_999"):
        generate_with(
            [make_curated_item()],
            report_payload(explanation("story_999")),
        )


def test_missing_story_explanation_fails() -> None:
    with pytest.raises(ReportError, match="omitted story IDs: story_002"):
        generate_with(
            [make_curated_item("First"), make_curated_item("Second")],
            report_payload(explanation("story_001")),
        )


def test_duplicate_story_explanation_fails() -> None:
    with pytest.raises(ReportError, match="duplicate story ID: story_001"):
        generate_with(
            [make_curated_item()],
            report_payload(
                explanation("story_001"),
                explanation("story_001"),
            ),
        )


def test_invalid_concept_related_story_id_fails() -> None:
    payload = report_payload(
        explanation("story_001"),
        concepts=[
            {
                "name": "Chiplets",
                "explanation": "Multiple dies connected in one package.",
                "related_story_ids": ["story_999"],
            }
        ],
    )

    with pytest.raises(ReportError, match="unknown story IDs: story_999"):
        generate_with([make_curated_item()], payload)


def test_final_markdown_title_is_correct() -> None:
    markdown, _ = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert markdown.startswith("# AI & Computer Engineering Weekly\n")


def test_date_range_is_rendered_exactly() -> None:
    markdown, _ = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert "**Week:** 2026-08-30 — 2026-09-05" in markdown


def test_story_order_follows_curated_item_order() -> None:
    markdown, _ = generate_with(
        [make_curated_item("Zeta"), make_curated_item("Alpha")],
        report_payload(explanation("story_001"), explanation("story_002")),
    )

    assert markdown.index("### 1. Zeta") < markdown.index("### 2. Alpha")


def test_category_and_organization_are_rendered() -> None:
    item = make_curated_item(
        category="robotics / physical AI",
        organization="Robotics Lab",
    )

    markdown, _ = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    assert "**Category:** robotics / physical AI" in markdown
    assert "**Organization:** Robotics Lab" in markdown


def test_what_happened_is_exact_upstream_summary() -> None:
    summary = "Upstream summary with authoritative wording and  two spaces."
    item = make_curated_item(summary=summary)

    markdown, _ = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    what_happened = markdown.split("#### What happened?\n\n", 1)[1].split(
        "\n\n#### Key technical details", 1
    )[0]
    assert what_happened == summary


def test_technical_details_are_exact_and_deterministically_ordered() -> None:
    details = ["First exact detail.", "Second exact detail."]
    item = make_curated_item(technical_details=details)

    markdown, _ = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    section = markdown.split("#### Key technical details\n\n", 1)[1].split(
        "\n\n#### What is it?", 1
    )[0]
    assert section == "- First exact detail.\n- Second exact detail."


def test_missing_organization_renders_neutral_text() -> None:
    markdown, _ = generate_with(
        [make_curated_item(organization=None)],
        report_payload(explanation("story_001")),
    )

    assert "**Organization:** Unknown / not specified" in markdown


def test_known_published_date_renders_exactly() -> None:
    markdown, _ = generate_with(
        [make_curated_item(published_date=date(2026, 9, 4))],
        report_payload(explanation("story_001")),
    )

    assert "**Date:** 2026-09-04" in markdown


def test_null_published_date_does_not_fabricate_a_date() -> None:
    markdown, _ = generate_with(
        [make_curated_item(published_date=None)],
        report_payload(explanation("story_001")),
    )

    assert "**Date:** Date not reliably established" in markdown


@pytest.mark.parametrize("story_count", [1, 4, 5, 7])
def test_at_a_glance_uses_at_most_first_five_curated_stories(
    story_count: int,
) -> None:
    items = [
        make_curated_item(
            f"Story {index}",
            organization=f"Lab {index}",
            published_date=date(2026, 9, min(index, 5)),
        )
        for index in range(1, story_count + 1)
    ]
    content = parsed_content(
        *(explanation(f"story_{index:03d}") for index in range(1, story_count + 1))
    )

    markdown = render_markdown(DATE_RANGE, items, content)
    glance = markdown.split("## This Week at a Glance\n\n", 1)[1].split(
        "\n\n## Major Updates", 1
    )[0]
    lines = glance.splitlines()

    assert len(lines) == min(story_count, 5)
    assert lines == [
        f"- **2026-09-{min(index, 5):02d} — Lab {index}:** Story {index}"
        for index in range(1, min(story_count, 5) + 1)
    ]
    if story_count > 5:
        assert "Story 6" not in glance


def test_at_a_glance_uses_unknown_value_fallbacks() -> None:
    item = make_curated_item(organization=None, published_date=None)
    content = parsed_content(explanation("story_001"))

    markdown = render_markdown(DATE_RANGE, [item], content)

    assert (
        "- **Date not reliably established — Unknown / not specified:** "
        "Example release"
    ) in markdown


def test_curation_score_has_deterministic_format() -> None:
    markdown, _ = generate_with(
        [make_curated_item(final_score=4.2)],
        report_payload(explanation("story_001")),
    )

    assert "**Curation Score:** 4.20 / 5" in markdown


def test_known_benchmark_uses_exact_upstream_information() -> None:
    item = make_curated_item(
        benchmark_information="Paper-reported throughput was 120 tokens/s."
    )

    markdown, _ = generate_with(
        [item],
        report_payload(explanation("story_001")),
    )

    assert "Paper-reported throughput was 120 tokens/s." in markdown


def test_null_benchmark_always_uses_explicit_safe_text() -> None:
    markdown, _ = generate_with(
        [make_curated_item(benchmark_information=None)],
        report_payload(explanation("story_001")),
    )

    assert NO_BENCHMARK_INFORMATION in markdown


def test_source_urls_come_from_news_item_sources() -> None:
    source = make_source(
        "Validated paper",
        "https://papers.example/research",
        "paper",
    )

    markdown, _ = generate_with(
        [make_curated_item(sources=[source])],
        report_payload(explanation("story_001")),
    )

    assert "[Validated paper](https://papers.example/research) — paper" in markdown


def test_model_generated_url_is_rejected_before_rendering() -> None:
    malicious = explanation(
        "story_001",
        what_it_is="Use https://unvalidated.example as a replacement source.",
    )

    with pytest.raises(ReportError, match="must not contain URLs"):
        generate_with([make_curated_item()], report_payload(malicious))


def test_primary_source_order_is_deterministic_and_unknown_types_render() -> None:
    sources = [
        make_source("Secondary", "https://example.com/secondary", "secondary"),
        make_source("Unknown", "https://example.com/unknown", "archive"),
        make_source("GitHub", "https://example.com/github", "github"),
        make_source("Official", "https://example.com/official", "official"),
        make_source("Paper", "https://example.com/paper", "paper"),
        make_source("University", "https://example.com/university", "university"),
        make_source("Benchmark", "https://example.com/benchmark", "benchmark"),
    ]

    markdown, _ = generate_with(
        [make_curated_item(sources=sources)],
        report_payload(explanation("story_001")),
    )
    story_sources = markdown.split("#### Sources\n\n", 1)[1].split(
        "## Source Index", 1
    )[0]

    ordered_titles = [
        "Official",
        "Paper",
        "GitHub",
        "University",
        "Benchmark",
        "Secondary",
        "Unknown",
    ]
    positions = [story_sources.index(f"[{title}]") for title in ordered_titles]
    assert positions == sorted(positions)
    assert "[Unknown](https://example.com/unknown) — archive" in story_sources


def test_source_index_deduplicates_normalized_urls() -> None:
    first = make_curated_item(
        "First",
        sources=[
            make_source(
                "Secondary copy",
                "https://EXAMPLE.com/shared/#fragment",
                "secondary",
            )
        ],
    )
    second = make_curated_item(
        "Second",
        sources=[
            make_source(
                "Official copy",
                "https://example.com/shared",
                "official",
            )
        ],
    )

    markdown, _ = generate_with(
        [first, second],
        report_payload(explanation("story_001"), explanation("story_002")),
    )
    source_index = markdown.split("## Source Index\n\n", 1)[1]

    assert source_index.count("example.com/shared") == 1
    assert "Official copy" in source_index
    assert "Secondary copy" not in source_index


def test_final_markdown_is_deterministic() -> None:
    item = make_curated_item()
    content = parsed_content(explanation("story_001"))

    first = render_markdown(DATE_RANGE, [item], content)
    second = render_markdown(DATE_RANGE, [item], content)

    assert first == second


def test_concepts_worth_learning_renders_structured_concepts() -> None:
    content = parsed_content(
        explanation("story_001"),
        concepts=[
            {
                "name": "Memory hierarchy",
                "explanation": "Caches trade capacity for access latency.",
                "related_story_ids": ["story_001"],
            }
        ],
    )

    markdown = render_markdown(DATE_RANGE, [make_curated_item()], content)

    assert "## Concepts Worth Learning" in markdown
    assert "### Memory hierarchy" in markdown
    assert "Caches trade capacity for access latency." in markdown
    assert "**Related updates:** #1 Example release" in markdown


def test_empty_concept_output_is_valid() -> None:
    markdown, _ = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001"), concepts=[]),
    )

    assert "## Concepts Worth Learning" not in markdown
    assert "## Source Index" in markdown


def test_api_exception_becomes_clear_report_error() -> None:
    responses = FakeResponses(error=RuntimeError("provider unavailable"))

    with pytest.raises(ReportError, match="OpenAI report request failed"):
        generate_report(
            DATE_RANGE,
            [make_curated_item()],
            configured_app(),
            client=FakeClient(responses),
        )


def test_missing_configuration_fails_before_request() -> None:
    responses = FakeResponses(error=AssertionError("must not be called"))

    with pytest.raises(ReportError, match="OPENAI_API_KEY, OPENAI_MODEL"):
        generate_report(
            DATE_RANGE,
            [make_curated_item()],
            AppConfig(),
            client=FakeClient(responses),
        )

    assert responses.calls == []


def test_missing_structured_output_fails_clearly() -> None:
    with pytest.raises(ReportError, match="no structured report content"):
        generate_with([make_curated_item()], None)


def test_invalid_structured_output_fails_clearly() -> None:
    with pytest.raises(ReportError, match="Invalid structured report response"):
        generate_with([make_curated_item()], {"concepts": []})


def test_save_report_uses_iso_week_filename_and_creates_directory(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "nested" / "reports"

    saved_path = save_report(DATE_RANGE, "# Report\n", output_dir)

    assert saved_path == output_dir / "2026-W36.md"
    assert saved_path.read_text(encoding="utf-8") == "# Report\n"


def test_saved_report_is_valid_utf8_markdown(tmp_path: Path) -> None:
    markdown = "# AI & Computer Engineering Weekly\n\nChiplets — 芯粒\n"

    saved_path = save_report(DATE_RANGE, markdown, tmp_path)

    assert saved_path.read_bytes().decode("utf-8") == markdown


def test_existing_report_is_not_overwritten_silently(tmp_path: Path) -> None:
    saved_path = save_report(DATE_RANGE, "original", tmp_path)

    with pytest.raises(ReportError, match="Report already exists"):
        save_report(DATE_RANGE, "replacement", tmp_path)

    assert saved_path.read_text(encoding="utf-8") == "original"


def test_failed_persistence_does_not_corrupt_existing_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_path = save_report(DATE_RANGE, "original", tmp_path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(report_module.os, "replace", fail_replace)

    with pytest.raises(ReportError, match="Could not save report"):
        save_report(DATE_RANGE, "replacement", tmp_path, overwrite=True)

    assert saved_path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_report_generation_never_uses_web_search() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert set(client.responses.calls[0]) == {"model", "input", "text_format"}


def test_report_content_accepts_small_concept_output() -> None:
    content = ReportContent(
        story_explanations=[StoryExplanation(**explanation("story_001"))],
        concepts=[
            ConceptExplanation(
                name="Quantization",
                explanation="Lower-precision values can reduce memory use.",
                related_story_ids=["story_001"],
            )
        ],
    )

    assert len(content.concepts) == 1
