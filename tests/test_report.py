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
            summary=f"Researched summary for {title}.",
            technical_details=[f"Technical detail for {title}."],
            benchmark_information=benchmark_information,
            sources=sources or [make_source()],
        ),
        final_score=final_score,
    )


def explanation(
    story_id: str,
    *,
    benchmark_explanation: str = "The supplied benchmark needs context.",
    what_happened: str | None = None,
) -> dict[str, Any]:
    return {
        "story_id": story_id,
        "what_happened": what_happened or f"What happened for {story_id}.",
        "what_is_it": f"What it is for {story_id}.",
        "why_it_matters": f"Why it matters for {story_id}.",
        "technical_explanation": f"Technical explanation for {story_id}.",
        "benchmark_explanation": benchmark_explanation,
        "student_takeaway": f"Student takeaway for {story_id}.",
    }


def report_payload(
    *explanations: dict[str, Any],
    summaries: list[str] | None = None,
    concepts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "week_summary": summaries if summaries is not None else ["Weekly summary."],
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
    summaries: list[str] | None = None,
    concepts: list[dict[str, Any]] | None = None,
) -> ReportContent:
    return ReportContent.model_validate(
        report_payload(
            *explanations,
            summaries=summaries,
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

    assert "No stories passed the Version 0.1 curation threshold" in markdown
    assert responses.calls == []


def test_empty_report_includes_date_range() -> None:
    markdown = render_markdown(DATE_RANGE, [])

    assert "**Week:** 2026-08-30 — 2026-09-05" in markdown
    assert "## Major Updates" not in markdown


def test_configured_openai_model_is_used() -> None:
    _, client = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001")),
    )

    assert client.responses.calls[0]["model"] == MODEL
    assert client.responses.calls[0]["text_format"] is ReportContent


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


def test_report_prompt_contains_supplied_story_facts() -> None:
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
    assert "Company-reported latency was 12 ms." in prompt
    assert "Specific source" in prompt
    assert '"source_type": "benchmark"' in prompt


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
            explanation("story_002", what_happened="Second explanation."),
            explanation("story_001", what_happened="First explanation."),
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


def test_curation_score_has_deterministic_format() -> None:
    markdown, _ = generate_with(
        [make_curated_item(final_score=4.2)],
        report_payload(explanation("story_001")),
    )

    assert "**Curation Score:** 4.20 / 5" in markdown


def test_known_benchmark_uses_structured_explanation() -> None:
    item = make_curated_item(
        benchmark_information="Paper-reported throughput was 120 tokens/s."
    )

    markdown, _ = generate_with(
        [item],
        report_payload(
            explanation(
                "story_001",
                benchmark_explanation=(
                    "The paper-reported result depends on its test setup."
                ),
            )
        ),
    )

    assert "The paper-reported result depends on its test setup." in markdown


def test_null_benchmark_always_uses_explicit_safe_text() -> None:
    markdown, _ = generate_with(
        [make_curated_item(benchmark_information=None)],
        report_payload(
            explanation(
                "story_001",
                benchmark_explanation="Unsupported performance claim.",
            )
        ),
    )

    assert NO_BENCHMARK_INFORMATION in markdown
    assert "Unsupported performance claim." not in markdown


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
        what_happened="Use https://unvalidated.example as a replacement source.",
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


def test_empty_summary_output_is_valid() -> None:
    markdown, _ = generate_with(
        [make_curated_item()],
        report_payload(explanation("story_001"), summaries=[]),
    )

    assert "No concise weekly summary was generated." in markdown


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
        generate_with([make_curated_item()], {"week_summary": []})


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
        week_summary=["One story this week."],
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
