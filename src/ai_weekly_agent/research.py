"""Research candidates with the Responses API and validate them locally."""

from collections.abc import Mapping
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI
from pydantic import ValidationError

from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.dates import raw_research_filename
from ai_weekly_agent.models import (
    CategoryResearchResult,
    DateRange,
    NewsItem,
    ResearchRun,
    Source,
)


RESEARCH_CATEGORIES = (
    "AI model releases",
    "AI developer tools/frameworks",
    "AI research",
    "GPU / semiconductor / AI infrastructure",
    "robotics / physical AI",
    "other important computer engineering developments",
)

# Total built-in tool calls allowed per category response.
MAX_RESEARCH_TOOL_CALLS = 4

_AUDIENCE = (
    "a university Computer Engineering student who is relatively new to "
    "the AI industry"
)
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "research.md"


class ResearchError(RuntimeError):
    """Raised when research or raw-research persistence cannot complete."""


def research_category(
    date_range: DateRange,
    category: str,
    config: AppConfig,
    *,
    client: Any | None = None,
) -> CategoryResearchResult:
    """Research one category and return locally validated candidates."""
    model = _require_openai_configuration(config)
    if category not in RESEARCH_CATEGORIES:
        raise ResearchError(f"Unsupported research category: {category}")

    prompt = _render_prompt(date_range, category)
    api_client = client if client is not None else OpenAI(
        api_key=config.openai_api_key
    )

    try:
        response = api_client.responses.parse(
            model=model,
            tools=[{"type": "web_search"}],
            max_tool_calls=MAX_RESEARCH_TOOL_CALLS,
            include=["web_search_call.action.sources"],
            input=prompt,
            text_format=CategoryResearchResult,
        )
    except ValidationError as exc:
        raise ResearchError(
            f"Invalid structured research response for category: {category}"
        ) from exc
    except Exception as exc:
        raise ResearchError(
            f"OpenAI research request failed for category: {category}"
        ) from exc

    parsed_output = _value(response, "output_parsed")
    if parsed_output is None:
        raise ResearchError(
            f"OpenAI returned no structured research for category: {category}"
        )

    try:
        result = (
            parsed_output
            if isinstance(parsed_output, CategoryResearchResult)
            else CategoryResearchResult.model_validate(parsed_output)
        )
    except ValidationError as exc:
        raise ResearchError(
            f"Invalid structured research response for category: {category}"
        ) from exc

    if result.category != category:
        raise ResearchError(
            "Structured research category did not match the requested category: "
            f"expected {category!r}, received {result.category!r}"
        )

    for item in result.items:
        if item.category != category:
            raise ResearchError(
                "A research item category did not match its result category: "
                f"{item.title!r}"
            )

    allowed_urls = _web_search_urls(response)
    return _filter_candidates(result, date_range, allowed_urls)


def research_all_categories(
    date_range: DateRange,
    config: AppConfig,
    *,
    client: Any | None = None,
) -> ResearchRun:
    """Research all Version 0.1 categories sequentially in fixed order."""
    _require_openai_configuration(config)
    api_client = client if client is not None else OpenAI(
        api_key=config.openai_api_key
    )
    categories = [
        research_category(
            date_range,
            category,
            config,
            client=api_client,
        )
        for category in RESEARCH_CATEGORIES
    ]
    return ResearchRun(date_range=date_range, categories=categories)


def save_research_run(
    research_run: ResearchRun,
    output_dir: str | Path = Path("data/raw"),
) -> Path:
    """Atomically save validated research JSON under a date-based filename."""
    directory = Path(output_dir)
    target = directory / raw_research_filename(research_run.date_range)
    temporary_path: Path | None = None

    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(research_run.model_dump_json(indent=2))
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, target)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ResearchError(f"Could not save raw research to {target}") from exc

    return target


def _require_openai_configuration(config: AppConfig) -> str:
    try:
        config.require_openai_configuration()
    except ValueError as exc:
        raise ResearchError(str(exc)) from exc

    if config.openai_model is None:
        raise ResearchError("Missing required OpenAI configuration: OPENAI_MODEL")
    return config.openai_model


def _render_prompt(date_range: DateRange, category: str) -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResearchError(f"Could not read research prompt: {_PROMPT_PATH}") from exc

    return template.format(
        category=category,
        start_date=date_range.start.isoformat(),
        end_date=date_range.end.isoformat(),
        audience=_AUDIENCE,
    )


def _filter_candidates(
    result: CategoryResearchResult,
    date_range: DateRange,
    allowed_urls: set[str],
) -> CategoryResearchResult:
    retained_items: list[NewsItem] = []

    for item in result.items:
        if (
            item.published_date is not None
            and not date_range.start <= item.published_date <= date_range.end
        ):
            continue

        retained_sources = _supported_sources(item.sources, allowed_urls)
        if not retained_sources:
            continue

        retained_items.append(item.model_copy(update={"sources": retained_sources}))

    return CategoryResearchResult(category=result.category, items=retained_items)


def _supported_sources(
    sources: list[Source],
    allowed_urls: set[str],
) -> list[Source]:
    retained: list[Source] = []
    seen: set[str] = set()

    for source in sources:
        normalized_url = _normalize_url(source.url)
        if (
            normalized_url is None
            or normalized_url not in allowed_urls
            or normalized_url in seen
        ):
            continue
        seen.add(normalized_url)
        retained.append(source.model_copy(update={"url": normalized_url}))

    return retained


def _web_search_urls(response: object) -> set[str]:
    """Return normalized source URLs from completed web-search calls only."""
    urls: set[str] = set()
    output = _value(response, "output") or []

    for output_item in output:
        if (
            _value(output_item, "type") != "web_search_call"
            or _value(output_item, "status") != "completed"
        ):
            continue

        action = _value(output_item, "action")
        if action is None:
            continue

        for source in _value(action, "sources") or []:
            normalized_url = _normalize_url(_value(source, "url"))
            if normalized_url is not None:
                urls.add(normalized_url)

        normalized_action_url = _normalize_url(_value(action, "url"))
        if normalized_action_url is not None:
            urls.add(normalized_action_url)

    return urls


def _normalize_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if scheme not in {"http", "https"} or not netloc:
        return None

    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _value(container: object, field: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(field)
    return getattr(container, field, None)
