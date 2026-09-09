"""Hybrid deterministic and LLM-assisted curation for the weekly agent."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ValidationError

from ai_weekly_agent.config import AppConfig, create_openai_client
from ai_weekly_agent.models import (
    CurationAssessment,
    CuratedItem,
    NewsItem,
    ResearchRun,
)


# A score above neutral prevents middling candidates from becoming filler.
MIN_CURATED_SCORE = 3.25
MAX_CURATED_ITEMS = 12

# Only near-ties receive a category-diversity preference.
_DIVERSITY_SCORE_WINDOW = 0.25
_PRIMARY_SOURCE_TYPES = frozenset(
    {"official", "paper", "github", "university", "benchmark"}
)
_SURROUNDING_TITLE_PUNCTUATION = " \t\r\n.,!?;:'\"()[]{}<>-–—"
_AUDIENCE = (
    "a university Computer Engineering student who is learning about "
    "the AI industry"
)
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "curate.md"


class CuratorError(RuntimeError):
    """Raised when curation cannot produce a validated result."""


class _CurationResponse(BaseModel):
    assessments: list[CurationAssessment]


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    item: NewsItem
    input_index: int


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: _Candidate
    assessment: CurationAssessment
    final_score: float


def curate_research_run(
    research_run: ResearchRun,
    config: AppConfig,
    *,
    client: Any | None = None,
) -> list[CuratedItem]:
    """Curate a research run with one semantic-assessment request at most."""
    candidates = _prepare_candidates(research_run)
    if not candidates:
        return []

    model = _require_openai_configuration(config)
    prompt = _render_prompt(candidates)
    api_client = client if client is not None else create_openai_client(config)

    try:
        response = api_client.responses.parse(
            model=model,
            input=prompt,
            text_format=_CurationResponse,
        )
    except ValidationError as exc:
        raise CuratorError("Invalid structured curation response") from exc
    except Exception as exc:
        raise CuratorError("OpenAI curation request failed") from exc

    parsed_output = _value(response, "output_parsed")
    if parsed_output is None:
        raise CuratorError("OpenAI returned no structured curation assessment")

    try:
        if isinstance(parsed_output, BaseModel):
            parsed_output = parsed_output.model_dump(mode="python")
        parsed = _CurationResponse.model_validate(parsed_output)
    except ValidationError as exc:
        raise CuratorError("Invalid structured curation response") from exc

    assessments = _validate_assessments(parsed.assessments, candidates)
    scored = [
        _ScoredCandidate(
            candidate=candidate,
            assessment=assessments[candidate.candidate_id],
            final_score=calculate_final_score(
                assessments[candidate.candidate_id]
            ),
        )
        for candidate in candidates
    ]
    representatives = _resolve_semantic_duplicates(scored)
    selected = _select_with_diversity(
        [
            candidate
            for candidate in representatives
            if candidate.final_score >= MIN_CURATED_SCORE
        ]
    )
    return [
        CuratedItem(
            item=candidate.candidate.item,
            final_score=candidate.final_score,
        )
        for candidate in selected
    ]


def calculate_final_score(assessment: CurationAssessment) -> float:
    """Return the equal-weight mean of the four curation dimensions."""
    return (
        assessment.impact
        + assessment.technical_significance
        + assessment.novelty
        + assessment.student_relevance
    ) / 4


def _prepare_candidates(research_run: ResearchRun) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    input_index = 0

    for category_result in research_run.categories:
        for item in category_result.items:
            input_index += 1
            candidate = _Candidate(
                candidate_id=f"candidate_{input_index:03d}",
                item=item,
                input_index=input_index,
            )
            if _passes_hard_filters(candidate.item, research_run):
                candidates.append(candidate)

    return _deduplicate_exact_candidates(candidates)


def _passes_hard_filters(item: NewsItem, research_run: ResearchRun) -> bool:
    if (
        not _normalize_title(item.title)
        or not _normalize_title(item.category)
        or not _has_text(item.summary)
    ):
        return False
    if not item.sources or not all(
        _has_text(source.title)
        and _has_text(source.url)
        and _has_text(source.source_type)
        for source in item.sources
    ):
        return False
    if item.published_date is None:
        return True
    try:
        return (
            research_run.date_range.start
            <= item.published_date
            <= research_run.date_range.end
        )
    except TypeError:
        return False


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _deduplicate_exact_candidates(
    candidates: list[_Candidate],
) -> list[_Candidate]:
    groups: list[list[_Candidate]] = []
    for candidate in candidates:
        matching_group = next(
            (
                group
                for group in groups
                if any(
                    _are_exact_duplicates(candidate, member)
                    for member in group
                )
            ),
            None,
        )
        if matching_group is None:
            groups.append([candidate])
        else:
            matching_group.append(candidate)

    representatives = [
        max(group, key=_exact_representative_key) for group in groups
    ]
    return sorted(representatives, key=lambda candidate: candidate.input_index)


def _are_exact_duplicates(left: _Candidate, right: _Candidate) -> bool:
    if _normalize_title(left.item.title) == _normalize_title(right.item.title):
        return True

    shared_urls = _source_urls(left.item) & _source_urls(right.item)
    same_organization = (
        _normalize_optional_text(left.item.organization)
        and _normalize_optional_text(left.item.organization)
        == _normalize_optional_text(right.item.organization)
    )
    same_category = _normalize_title(left.item.category) == _normalize_title(
        right.item.category
    )
    dates_do_not_conflict = (
        left.item.published_date is None
        or right.item.published_date is None
        or left.item.published_date == right.item.published_date
    )
    return bool(
        shared_urls
        and same_organization
        and same_category
        and dates_do_not_conflict
    )


def _exact_representative_key(candidate: _Candidate) -> tuple[int, int, int, int]:
    return (
        len(candidate.item.sources),
        int(candidate.item.published_date is not None),
        sum(
            len(detail.strip())
            for detail in (candidate.item.technical_details or [])
            if isinstance(detail, str)
        ),
        -candidate.input_index,
    )


def _normalize_title(value: str) -> str:
    return " ".join(
        value.casefold().strip(_SURROUNDING_TITLE_PUNCTUATION).split()
    )


def _normalize_optional_text(value: str | None) -> str:
    return " ".join(value.casefold().split()) if value else ""


def _source_urls(item: NewsItem) -> set[str]:
    return {
        normalized
        for source in item.sources
        if (normalized := _normalize_url(source.url)) is not None
    }


def _normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except (AttributeError, ValueError):
        return None
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if scheme not in {"http", "https"} or not netloc:
        return None
    return urlunsplit(
        (scheme, netloc, parsed.path.rstrip("/"), parsed.query, "")
    )


def _render_prompt(candidates: list[_Candidate]) -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise CuratorError(f"Could not read curation prompt: {_PROMPT_PATH}") from exc

    candidate_data = [
        {
            "candidate_id": candidate.candidate_id,
            "item": candidate.item.model_dump(mode="json"),
        }
        for candidate in candidates
    ]
    return template.format(
        audience=_AUDIENCE,
        candidates_json=json.dumps(
            candidate_data,
            ensure_ascii=False,
            indent=2,
        ),
    )


def _require_openai_configuration(config: AppConfig) -> str:
    try:
        config.require_openai_configuration()
    except ValueError as exc:
        raise CuratorError(str(exc)) from exc
    if config.openai_model is None:
        raise CuratorError("Missing required OpenAI configuration: OPENAI_MODEL")
    return config.openai_model


def _validate_assessments(
    assessments: list[CurationAssessment],
    candidates: list[_Candidate],
) -> dict[str, CurationAssessment]:
    expected_ids = {candidate.candidate_id for candidate in candidates}
    by_id: dict[str, CurationAssessment] = {}

    for assessment in assessments:
        if assessment.candidate_id not in expected_ids:
            raise CuratorError(
                "Curation assessment returned unknown candidate ID: "
                f"{assessment.candidate_id}"
            )
        if assessment.candidate_id in by_id:
            raise CuratorError(
                "Curation assessment returned duplicate candidate ID: "
                f"{assessment.candidate_id}"
            )
        by_id[assessment.candidate_id] = assessment

    missing_ids = expected_ids - by_id.keys()
    if missing_ids:
        raise CuratorError(
            "Curation assessment omitted candidate IDs: "
            + ", ".join(sorted(missing_ids))
        )

    for assessment in assessments:
        duplicate_id = assessment.semantic_duplicate_of
        if duplicate_id is None:
            continue
        if duplicate_id not in expected_ids:
            raise CuratorError(
                "Curation assessment referenced unknown semantic duplicate: "
                f"{duplicate_id}"
            )
        if duplicate_id == assessment.candidate_id:
            raise CuratorError(
                "A candidate cannot be a semantic duplicate of itself: "
                f"{duplicate_id}"
            )

    return by_id


def _resolve_semantic_duplicates(
    scored: list[_ScoredCandidate],
) -> list[_ScoredCandidate]:
    """Resolve connected duplicate groups with one deterministic winner each."""
    groups = [
        {candidate.candidate.candidate_id} for candidate in scored
    ]
    for candidate in scored:
        duplicate_id = candidate.assessment.semantic_duplicate_of
        if duplicate_id is None:
            continue
        candidate_group = next(
            group
            for group in groups
            if candidate.candidate.candidate_id in group
        )
        duplicate_group = next(
            group for group in groups if duplicate_id in group
        )
        if candidate_group is not duplicate_group:
            candidate_group.update(duplicate_group)
            groups.remove(duplicate_group)

    scored_by_id = {
        candidate.candidate.candidate_id: candidate for candidate in scored
    }
    winners = [
        max(
            (scored_by_id[candidate_id] for candidate_id in group),
            key=_semantic_representative_key,
        )
        for group in groups
    ]
    return sorted(
        winners,
        key=lambda candidate: candidate.candidate.input_index,
    )


def _semantic_representative_key(
    candidate: _ScoredCandidate,
) -> tuple[float, int, int, int, int]:
    return (
        candidate.final_score,
        _primary_source_count(candidate.candidate.item),
        len(candidate.candidate.item.sources),
        int(candidate.candidate.item.published_date is not None),
        -candidate.candidate.input_index,
    )


def _primary_source_count(item: NewsItem) -> int:
    return sum(
        source.source_type.casefold() in _PRIMARY_SOURCE_TYPES
        for source in item.sources
    )


def _selection_sort_key(
    candidate: _ScoredCandidate,
) -> tuple[float, int, int, int, int]:
    representative_key = _semantic_representative_key(candidate)
    return tuple(-value for value in representative_key[:-1]) + (
        candidate.candidate.input_index,
    )


def _select_with_diversity(
    candidates: list[_ScoredCandidate],
) -> list[_ScoredCandidate]:
    """Prefer underrepresented categories only among candidates within 0.25."""
    remaining = sorted(candidates, key=_selection_sort_key)
    selected: list[_ScoredCandidate] = []
    category_counts: Counter[str] = Counter()

    while remaining and len(selected) < MAX_CURATED_ITEMS:
        top_score = remaining[0].final_score
        close_candidates = [
            candidate
            for candidate in remaining
            if top_score - candidate.final_score <= _DIVERSITY_SCORE_WINDOW
        ]
        chosen = min(
            close_candidates,
            key=lambda candidate: (
                category_counts[candidate.candidate.item.category],
                *_selection_sort_key(candidate),
            ),
        )
        selected.append(chosen)
        category_counts[chosen.candidate.item.category] += 1
        remaining.remove(chosen)

    return selected


def _value(container: object, field: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(field)
    return getattr(container, field, None)
