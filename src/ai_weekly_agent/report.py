"""Structured report explanations and deterministic Markdown output."""

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from ai_weekly_agent.config import AppConfig, create_openai_client
from ai_weekly_agent.dates import weekly_report_filename
from ai_weekly_agent.models import CuratedItem, DateRange, Source


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

NO_BENCHMARK_INFORMATION = (
    "No reliable benchmark information was available in the researched sources."
)
NO_TECHNICAL_DETAILS = (
    "No additional technical details were available in the researched sources."
)
_UNKNOWN_ORGANIZATION = "Unknown / not specified"
_UNKNOWN_DATE = "Date not reliably established"
_AUDIENCE = (
    "a university Computer Engineering student who understands basic "
    "programming, computer architecture, data structures, embedded systems, "
    "and introductory AI concepts but may not know current AI industry "
    "terminology"
)
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "report.md"
_URL_PATTERN = re.compile(r"(?i)(?:https?://|www\.)\S+")
_SOURCE_TYPE_ORDER = {
    "official": 0,
    "paper": 1,
    "github": 2,
    "university": 3,
    "benchmark": 4,
    "secondary": 5,
}


class ReportError(RuntimeError):
    """Raised when report generation or persistence cannot complete safely."""


class StoryExplanation(BaseModel):
    """LLM-written interpretation for one supplied story."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    story_id: NonEmptyText
    what_it_is: NonEmptyText
    why_it_matters: NonEmptyText
    student_takeaway: NonEmptyText


class ConceptExplanation(BaseModel):
    """One beginner-friendly concept connected to supplied stories."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: NonEmptyText
    explanation: NonEmptyText
    related_story_ids: list[NonEmptyText] = Field(min_length=1)


class ReportContent(BaseModel):
    """Structured prose returned by the non-search report request."""

    model_config = ConfigDict(extra="forbid")

    story_explanations: list[StoryExplanation]
    concepts: list[ConceptExplanation] = Field(default_factory=list, max_length=5)


def generate_report(
    date_range: DateRange,
    curated_items: Sequence[CuratedItem],
    config: AppConfig,
    *,
    client: Any | None = None,
) -> str:
    """Generate explanations once, then render the report deterministically."""
    items = list(curated_items)
    if not items:
        return render_markdown(date_range, items)

    model = _require_openai_configuration(config)
    prompt = _render_prompt(date_range, items)
    api_client = client if client is not None else create_openai_client(config)

    try:
        response = api_client.responses.parse(
            model=model,
            input=prompt,
            text_format=ReportContent,
        )
    except ValidationError as exc:
        raise ReportError("Invalid structured report response") from exc
    except Exception as exc:
        raise ReportError("OpenAI report request failed") from exc

    parsed_output = _value(response, "output_parsed")
    if parsed_output is None:
        raise ReportError("OpenAI returned no structured report content")

    try:
        if isinstance(parsed_output, BaseModel):
            parsed_output = parsed_output.model_dump(mode="python")
        content = ReportContent.model_validate(parsed_output)
    except ValidationError as exc:
        raise ReportError("Invalid structured report response") from exc

    return render_markdown(date_range, items, content)


def render_markdown(
    date_range: DateRange,
    curated_items: Sequence[CuratedItem],
    content: ReportContent | None = None,
) -> str:
    """Render stable Markdown without accepting model-generated metadata."""
    items = list(curated_items)
    explanations: dict[str, StoryExplanation] = {}
    story_ids: list[str] = []
    if items:
        if content is None:
            raise ReportError(
                "Structured report content is required for non-empty input"
            )
        story_ids = [
            f"story_{index:03d}" for index in range(1, len(items) + 1)
        ]
        explanations = _validate_report_content(content, story_ids)

    lines = [
        "# AI & Computer Engineering Weekly",
        "",
        f"**Week:** {date_range.start.isoformat()} — {date_range.end.isoformat()}",
        "",
        "## This Week at a Glance",
        "",
    ]

    if not items:
        lines.append(
            "No stories passed the curation threshold for this period."
        )
        return "\n".join(lines) + "\n"

    lines.extend(_at_a_glance_lines(items))

    lines.extend(["", "## Major Updates", ""])
    for index, (story_id, curated_item) in enumerate(
        zip(story_ids, items, strict=True),
        start=1,
    ):
        item = curated_item.item
        explanation = explanations[story_id]
        organization = item.organization or _UNKNOWN_ORGANIZATION
        published_date = (
            item.published_date.isoformat()
            if item.published_date is not None
            else _UNKNOWN_DATE
        )
        benchmark_text = (
            item.benchmark_information
            if item.benchmark_information is not None
            else NO_BENCHMARK_INFORMATION
        )

        lines.extend(
            [
                f"### {index}. {_single_line(item.title)}",
                "",
                f"**Category:** {_single_line(item.category)}",
                f"**Organization:** {_single_line(organization)}",
                f"**Date:** {published_date}",
                f"**Curation Score:** {curated_item.final_score:.2f} / 5",
                "",
                "#### What happened?",
                "",
                item.summary,
                "",
                "#### Key technical details",
                "",
            ]
        )
        if item.technical_details:
            lines.extend(f"- {detail}" for detail in item.technical_details)
        else:
            lines.append(NO_TECHNICAL_DETAILS)
        lines.extend(
            [
                "",
                "#### What is it?",
                "",
                _paragraph(explanation.what_it_is),
                "",
                "#### Why does it matter?",
                "",
                _paragraph(explanation.why_it_matters),
                "",
                "#### Performance / benchmarks",
                "",
                benchmark_text,
                "",
                "#### What should I learn from this?",
                "",
                _paragraph(explanation.student_takeaway),
                "",
                "#### Sources",
                "",
            ]
        )
        lines.extend(
            _source_markdown(source)
            for source in _ordered_sources(item.sources)
        )
        lines.append("")

    if content.concepts:
        lines.extend(["## Concepts Worth Learning", ""])
        story_titles = {
            story_id: f"#{index} {_single_line(curated_item.item.title)}"
            for index, (story_id, curated_item) in enumerate(
                zip(story_ids, items, strict=True),
                start=1,
            )
        }
        for concept in content.concepts:
            related = ", ".join(
                story_titles[story_id] for story_id in concept.related_story_ids
            )
            lines.extend(
                [
                    f"### {_single_line(concept.name)}",
                    "",
                    _paragraph(concept.explanation),
                    "",
                    f"**Related updates:** {related}",
                    "",
                ]
            )

    lines.extend(["## Source Index", ""])
    for index, source in enumerate(_consolidated_sources(items), start=1):
        lines.append(
            f"{index}. {_source_link(source)} — "
            f"{_single_line(source.source_type)}"
        )

    return "\n".join(lines) + "\n"


def save_report(
    date_range: DateRange,
    markdown: str,
    output_dir: str | Path = Path("reports"),
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically save UTF-8 Markdown under its ISO-week filename."""
    directory = Path(output_dir)
    target = directory / weekly_report_filename(date_range)
    temporary_path: Path | None = None

    try:
        directory.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise ReportError(f"Report already exists: {target}")

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=directory,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(markdown)

        os.replace(temporary_path, target)
        temporary_path = None
    except ReportError:
        raise
    except OSError as exc:
        raise ReportError(f"Could not save report: {target}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return target


def _render_prompt(
    date_range: DateRange,
    curated_items: list[CuratedItem],
) -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Could not read report prompt: {_PROMPT_PATH}") from exc

    stories = []
    for index, curated_item in enumerate(curated_items, start=1):
        item = curated_item.item
        stories.append(
            {
                "story_id": f"story_{index:03d}",
                "title": item.title,
                "category": item.category,
                "summary": item.summary,
                "technical_details": item.technical_details,
            }
        )

    return template.format(
        audience=_AUDIENCE,
        start_date=date_range.start.isoformat(),
        end_date=date_range.end.isoformat(),
        stories_json=json.dumps(stories, ensure_ascii=False, indent=2),
    )


def _require_openai_configuration(config: AppConfig) -> str:
    try:
        config.require_openai_configuration()
    except ValueError as exc:
        raise ReportError(str(exc)) from exc
    if config.openai_model is None:
        raise ReportError("Missing required OpenAI configuration: OPENAI_MODEL")
    return config.openai_model


def _validate_report_content(
    content: ReportContent,
    expected_ids: list[str],
) -> dict[str, StoryExplanation]:
    expected = set(expected_ids)
    explanations: dict[str, StoryExplanation] = {}

    for explanation in content.story_explanations:
        if explanation.story_id not in expected:
            raise ReportError(
                "Report content returned unknown story ID: "
                f"{explanation.story_id}"
            )
        if explanation.story_id in explanations:
            raise ReportError(
                "Report content returned duplicate story ID: "
                f"{explanation.story_id}"
            )
        explanations[explanation.story_id] = explanation

    missing = expected - explanations.keys()
    if missing:
        raise ReportError(
            "Report content omitted story IDs: " + ", ".join(sorted(missing))
        )

    for concept in content.concepts:
        unknown_ids = set(concept.related_story_ids) - expected
        if unknown_ids:
            raise ReportError(
                "Report concept referenced unknown story IDs: "
                + ", ".join(sorted(unknown_ids))
            )

    for text in _report_text_values(content):
        if _URL_PATTERN.search(text):
            raise ReportError("Model-generated report content must not contain URLs")

    return explanations


def _report_text_values(content: ReportContent) -> list[str]:
    values: list[str] = []
    for explanation in content.story_explanations:
        values.extend(
            [
                explanation.what_it_is,
                explanation.why_it_matters,
                explanation.student_takeaway,
            ]
        )
    for concept in content.concepts:
        values.extend([concept.name, concept.explanation])
    return values


def _at_a_glance_lines(
    curated_items: Sequence[CuratedItem],
) -> list[str]:
    lines = []
    for curated_item in list(curated_items)[:5]:
        item = curated_item.item
        organization = item.organization or _UNKNOWN_ORGANIZATION
        published_date = (
            item.published_date.isoformat()
            if item.published_date is not None
            else _UNKNOWN_DATE
        )
        lines.append(
            f"- **{published_date} — {_single_line(organization)}:** "
            f"{_single_line(item.title)}"
        )
    return lines


def _ordered_sources(sources: Sequence[Source]) -> list[Source]:
    best_by_url: dict[str, tuple[Source, int]] = {}
    for index, source in enumerate(sources):
        key = _normalize_url(source.url) or source.url
        existing = best_by_url.get(key)
        if existing is None:
            best_by_url[key] = (source, index)
        elif _source_rank(source) < _source_rank(existing[0]):
            best_by_url[key] = (source, existing[1])

    return [
        source
        for source, _ in sorted(
            best_by_url.values(),
            key=lambda entry: (_source_rank(entry[0]), entry[1]),
        )
    ]


def _consolidated_sources(curated_items: Sequence[CuratedItem]) -> list[Source]:
    sources: list[Source] = []
    for curated_item in curated_items:
        sources.extend(curated_item.item.sources)
    return _ordered_sources(sources)


def _source_rank(source: Source) -> int:
    return _SOURCE_TYPE_ORDER.get(source.source_type.casefold(), 6)


def _normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except (AttributeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.query,
            "",
        )
    )


def _source_markdown(source: Source) -> str:
    return f"- {_source_link(source)} — {_single_line(source.source_type)}"


def _source_link(source: Source) -> str:
    label = _single_line(source.title).replace("\\", "\\\\")
    label = label.replace("[", "\\[").replace("]", "\\]")
    return f"[{label}]({source.url})"


def _paragraph(value: str) -> str:
    return " ".join(value.split())


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _value(container: object, field: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(field)
    return getattr(container, field, None)
