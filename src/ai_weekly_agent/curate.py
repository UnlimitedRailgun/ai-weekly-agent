"""Hybrid deterministic and LLM-assisted curation for the weekly agent."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_weekly_agent.config import AppConfig, create_openai_client
from ai_weekly_agent.history import (
    HistoryLoadResult,
    HistoryLoadState,
    retrieve_historical_candidates,
)
from ai_weekly_agent.models import (
    CurationAssessment,
    CuratedItem,
    CurrentFactReference,
    HistoricalContext,
    HistoricalMatch,
    HistoricalStatus,
    NewsItem,
    ORIGINAL_EVALUATION_SOURCE_TYPES,
    PRIMARY_EVIDENCE_SOURCE_TYPES,
    ResearchRun,
)
from ai_weekly_agent.research import normalize_source_url


# A score above neutral prevents middling candidates from becoming filler.
MIN_CURATED_SCORE = 3.25
MAX_CURATED_ITEMS = 12

# Only near-ties receive a category-diversity preference.
_DIVERSITY_SCORE_WINDOW = 0.25
_SURROUNDING_TITLE_PUNCTUATION = " \t\r\n.,!?;:'\"()[]{}<>-–—"
_AUDIENCE = (
    "a university Computer Engineering student who is learning about "
    "the AI industry"
)
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "curate.md"
_HISTORY_SECTION_START = "<!-- HISTORICAL_CONTINUITY_START -->"
_HISTORY_SECTION_END = "<!-- HISTORICAL_CONTINUITY_END -->"


class CuratorError(RuntimeError):
    """Raised when curation cannot produce a validated result."""


class _CurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[CurationAssessment]


class _NoHistoryCurationAssessment(BaseModel):
    """External Curate response shape when historical judgment is inapplicable."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    impact: int = Field(ge=1, le=5)
    technical_significance: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    student_relevance: int = Field(ge=1, le=5)
    semantic_duplicate_of: str | None = None


class _NoHistoryCurationResponse(BaseModel):
    """Strict collection returned for Curate requests without usable history."""

    model_config = ConfigDict(extra="forbid")

    assessments: list[_NoHistoryCurationAssessment]


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


@dataclass
class CurationStatistics:
    """Content-free Curate execution facts populated as stages complete."""

    prepared_candidate_count: int | None = None
    matched_current_candidate_count: int | None = None
    validated_status_counts: dict[HistoricalStatus, int] | None = None
    repeats_suppressed: int | None = None
    selected_follow_up_count: int | None = None


def curate_research_run(
    research_run: ResearchRun,
    config: AppConfig,
    *,
    client: Any | None = None,
    history: HistoryLoadResult | None = None,
    statistics: CurationStatistics | None = None,
) -> list[CuratedItem]:
    """Curate a research run with one semantic-assessment request at most."""
    if statistics is not None:
        _reset_statistics(statistics)
    candidates = _prepare_candidates(research_run)
    if statistics is not None:
        statistics.prepared_candidate_count = len(candidates)
    if not candidates:
        if (
            statistics is not None
            and history is not None
            and history.state != "unavailable"
        ):
            statistics.matched_current_candidate_count = 0
        return []

    history_state, history_matches = _prepare_historical_matches(
        candidates, history
    )
    if statistics is not None and history_state is not None:
        statistics.matched_current_candidate_count = sum(
            bool(matches) for matches in history_matches.values()
        )
    model = _require_openai_configuration(config)
    prompt = _render_prompt(candidates, history_state, history_matches)
    api_client = client if client is not None else create_openai_client(config)
    response_format = (
        _NoHistoryCurationResponse
        if history_state is None
        else _CurationResponse
    )

    try:
        response = api_client.responses.parse(
            model=model,
            input=prompt,
            text_format=response_format,
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
        parsed = response_format.model_validate(parsed_output)
    except ValidationError as exc:
        raise CuratorError("Invalid structured curation response") from exc

    if isinstance(parsed, _NoHistoryCurationResponse):
        parsed_assessments = [
            _adapt_no_history_assessment(assessment)
            for assessment in parsed.assessments
        ]
    else:
        parsed_assessments = parsed.assessments

    assessments = _validate_assessments(
        parsed_assessments,
        candidates,
        history_state=history_state,
        history_matches=history_matches,
    )
    if statistics is not None and history_state is not None:
        status_counts: Counter[HistoricalStatus] = Counter(
            assessment.historical_status
            for assessment in assessments.values()
            if assessment.historical_status is not None
        )
        statistics.validated_status_counts = {
            status: status_counts[status]
            for status in ("NEW", "FOLLOW_UP", "REPEAT", "UNCERTAIN")
        }
        statistics.repeats_suppressed = status_counts["REPEAT"]
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
    non_repeats = [
        candidate
        for candidate in scored
        if candidate.assessment.historical_status != "REPEAT"
    ]
    representatives = _resolve_semantic_duplicates(non_repeats)
    selected = _select_with_diversity(
        [
            candidate
            for candidate in representatives
            if candidate.final_score >= MIN_CURATED_SCORE
        ]
    )
    if statistics is not None and history_state is not None:
        statistics.selected_follow_up_count = sum(
            candidate.assessment.historical_status == "FOLLOW_UP"
            for candidate in selected
        )
    return [
        CuratedItem(
            item=candidate.candidate.item,
            final_score=candidate.final_score,
            historical_context=_build_historical_context(
                candidate,
                history_matches.get(candidate.candidate.candidate_id, ()),
            ),
        )
        for candidate in selected
    ]


def _adapt_no_history_assessment(
    assessment: _NoHistoryCurationAssessment,
) -> CurationAssessment:
    """Convert the narrow external shape without mutating parsed output."""
    return CurationAssessment(
        candidate_id=assessment.candidate_id,
        impact=assessment.impact,
        technical_significance=assessment.technical_significance,
        novelty=assessment.novelty,
        student_relevance=assessment.student_relevance,
        semantic_duplicate_of=assessment.semantic_duplicate_of,
        historical_status=None,
        historical_match_id=None,
        material_change_refs=[],
    )


def _reset_statistics(statistics: CurationStatistics) -> None:
    statistics.prepared_candidate_count = None
    statistics.matched_current_candidate_count = None
    statistics.validated_status_counts = None
    statistics.repeats_suppressed = None
    statistics.selected_follow_up_count = None


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
    # Anchor groups are established independently, never by overlapping URLs.
    anchor_groups: dict[tuple[str, date], list[_Candidate]] = {}
    singletons: list[_Candidate] = []
    for candidate in candidates:
        anchor = _event_anchor(candidate.item)
        if anchor is None:
            singletons.append(candidate)
        else:
            anchor_groups.setdefault(anchor, []).append(candidate)

    # Finalized anchor groups cannot be bridged into title groups. Their members
    # may have different titles/organizations, so using a representative's title
    # as a new group identity would discard the original identity safeguards.
    groups = [group for group in anchor_groups.values() if len(group) > 1]
    singletons.extend(
        group[0] for group in anchor_groups.values() if len(group) == 1
    )
    title_groups: list[list[_Candidate]] = []
    for candidate in sorted(singletons, key=lambda entry: entry.input_index):
        matches = [
            group for group in title_groups
            if all(
                _same_title_event(candidate.item, member.item) for member in group
            )
        ]
        if len(matches) == 1:
            matches[0].append(candidate)
        else:
            # An undated record can match multiple conflicting dated groups.
            # Keep ambiguous records separate rather than connect those groups.
            title_groups.append([candidate])
    groups.extend(title_groups)

    representatives = [
        max(group, key=_exact_representative_key) for group in groups
    ]
    return sorted(representatives, key=lambda candidate: candidate.input_index)


def _event_anchor(item: NewsItem) -> tuple[str, date] | None:
    """Return the first explicit primary summary/event URL and known date."""
    if item.published_date is None:
        return None
    for source in item.sources:
        if (
            source.source_type.casefold() in PRIMARY_EVIDENCE_SOURCE_TYPES
            and source.fact_support is not None
            and source.fact_support.summary
            and "event" in (source.evidence_roles or [])
            and (url := normalize_source_url(source.url)) is not None
        ):
            return url, item.published_date
    return None


def _same_title_event(left: NewsItem, right: NewsItem) -> bool:
    organization = _normalize_optional_text(left.organization)
    if (
        not organization
        or organization != _normalize_optional_text(right.organization)
        or _normalize_title(left.title) != _normalize_title(right.title)
    ):
        return False
    if (
        left.published_date is not None
        and right.published_date is not None
        and left.published_date != right.published_date
    ):
        return False
    left_anchor, right_anchor = _event_anchor(left), _event_anchor(right)
    return left_anchor is None or right_anchor is None or left_anchor == right_anchor


def _explicit_evidence_counts(item: NewsItem) -> tuple[int, int]:
    """Count reported supporting URLs, not background or prose quantity.

    This is a structural preference for already verified inputs, not a second
    verification engine. Benchmark originals qualify only as benchmark support.
    """
    primary_urls: set[str] = set()
    supporting_urls: set[str] = set()
    for source in item.sources:
        support = source.fact_support
        url = normalize_source_url(source.url)
        if support is None or url is None:
            continue
        roles = source.evidence_roles or []
        primary = source.source_type.casefold() in PRIMARY_EVIDENCE_SOURCE_TYPES
        supports_facts = (
            (support.summary and "event" in roles)
            or (item.published_date is not None and "event_date" in roles)
            or (bool(support.technical_detail_indices) and "technical" in roles)
        )
        supports_benchmark = (
            support.benchmark
            and "benchmark" in roles
            and bool(item.benchmark_information)
        )
        if primary and supports_facts:
            primary_urls.add(url)
        if (
            supports_facts
            and (primary or source.source_type.casefold() == "secondary")
        ) or (
            supports_benchmark
            and source.source_type.casefold() in ORIGINAL_EVALUATION_SOURCE_TYPES
        ):
            supporting_urls.add(url)
    return len(primary_urls), len(supporting_urls)


def _exact_representative_key(
    candidate: _Candidate,
) -> tuple[int, int, int, int, int]:
    return (
        int(
            all(
                source.fact_support is not None
                and source.evidence_roles is not None
                for source in candidate.item.sources
            )
        ),
        *_explicit_evidence_counts(candidate.item),
        int(candidate.item.published_date is not None),
        -candidate.input_index,
    )


def _normalize_title(value: str) -> str:
    return " ".join(
        value.casefold().strip(_SURROUNDING_TITLE_PUNCTUATION).split()
    )


def _normalize_optional_text(value: str | None) -> str:
    return " ".join(value.casefold().split()) if value else ""


def _prepare_historical_matches(
    candidates: list[_Candidate],
    history: HistoryLoadResult | None,
) -> tuple[HistoryLoadState | None, dict[str, tuple[HistoricalMatch, ...]]]:
    if history is None or history.state == "unavailable":
        return None, {}

    return history.state, {
        candidate.candidate_id: tuple(
            retrieve_historical_candidates(candidate.item, history.stories)
        )
        for candidate in candidates
    }


def _render_prompt(
    candidates: list[_Candidate],
    history_state: HistoryLoadState | None,
    history_matches: Mapping[str, tuple[HistoricalMatch, ...]],
) -> str:
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise CuratorError(f"Could not read curation prompt: {_PROMPT_PATH}") from exc

    template = _configure_history_prompt(template, history_state is not None)
    candidate_data = []
    for candidate in candidates:
        payload: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "item": candidate.item.model_dump(mode="json"),
        }
        if history_state is not None:
            payload["historical_candidates"] = [
                _historical_prompt_data(match)
                for match in history_matches[candidate.candidate_id]
            ]
        candidate_data.append(payload)

    return template.format(
        audience=_AUDIENCE,
        candidates_json=json.dumps(
            candidate_data,
            ensure_ascii=False,
            indent=2,
        ),
    )


def _configure_history_prompt(template: str, enabled: bool) -> str:
    start = template.find(_HISTORY_SECTION_START)
    end = template.find(_HISTORY_SECTION_END)
    if start < 0 or end < start:
        raise CuratorError("Curation prompt has invalid history section markers")
    section_end = end + len(_HISTORY_SECTION_END)
    if enabled:
        return (
            template[:start]
            + template[start + len(_HISTORY_SECTION_START):end]
            + template[section_end:]
        )
    return template[:start] + template[section_end:]


def _historical_prompt_data(match: HistoricalMatch) -> dict[str, object]:
    story = match.story
    item = story.item
    return {
        "history_id": story.history_id,
        "prior_report_date_range": story.report_date_range.model_dump(mode="json"),
        "report_position": story.report_position,
        "match_reasons": match.match_reasons,
        "item": {
            "title": item.title,
            "category": item.category,
            "organization": item.organization,
            "published_date": (
                item.published_date.isoformat()
                if item.published_date is not None
                else None
            ),
            "summary": item.summary,
            "technical_details": item.technical_details,
            "benchmark_information": item.benchmark_information,
        },
    }


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
    *,
    history_state: HistoryLoadState | None = None,
    history_matches: Mapping[str, tuple[HistoricalMatch, ...]] | None = None,
) -> dict[str, CurationAssessment]:
    history_matches = history_matches or {}
    expected_ids = {candidate.candidate_id for candidate in candidates}
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in candidates
    }
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

    validated: dict[str, CurationAssessment] = {}
    for candidate_id, assessment in by_id.items():
        matches = history_matches.get(candidate_id, ())
        if history_state is None:
            if assessment.historical_status is not None:
                raise CuratorError(
                    "Curation assessment supplied historical judgment when "
                    f"none was requested: {candidate_id}"
                )
            validated[candidate_id] = assessment
            continue

        if not matches:
            if assessment.historical_status is not None:
                raise CuratorError(
                    "Curation assessment overrode a local historical status: "
                    f"{candidate_id}"
                )
            local_status: HistoricalStatus = (
                "NEW" if history_state == "complete" else "UNCERTAIN"
            )
            validated[candidate_id] = CurationAssessment.model_validate(
                {
                    **assessment.model_dump(mode="python"),
                    "historical_status": local_status,
                }
            )
            continue

        if assessment.historical_status is None:
            raise CuratorError(
                "Curation assessment omitted matched historical status: "
                f"{candidate_id}"
            )
        supplied_match_ids = {
            match.story.history_id for match in matches
        }
        if (
            assessment.historical_match_id is not None
            and assessment.historical_match_id not in supplied_match_ids
        ):
            raise CuratorError(
                "Curation assessment referenced unknown historical match: "
                f"{assessment.historical_match_id}"
            )
        for reference in assessment.material_change_refs:
            _resolve_current_fact(
                candidates_by_id[candidate_id].item, reference
            )
        validated[candidate_id] = assessment

    return validated


def _resolve_current_fact(
    item: NewsItem, reference: CurrentFactReference
) -> str:
    if reference.field == "summary":
        return item.summary
    if reference.field == "benchmark_information":
        if not _has_text(item.benchmark_information):
            raise CuratorError(
                "Historical material-change reference targets unavailable "
                "benchmark information"
            )
        return item.benchmark_information

    index = reference.technical_detail_index
    if index is None or index >= len(item.technical_details):
        raise CuratorError(
            "Historical material-change reference has an out-of-range "
            "technical detail index"
        )
    detail = item.technical_details[index]
    if not _has_text(detail):
        raise CuratorError(
            "Historical material-change reference targets an empty "
            "technical detail"
        )
    return detail


def _build_historical_context(
    candidate: _ScoredCandidate,
    matches: tuple[HistoricalMatch, ...],
) -> HistoricalContext | None:
    assessment = candidate.assessment
    status = assessment.historical_status
    if status is None:
        return None

    matched = next(
        (
            match
            for match in matches
            if match.story.history_id == assessment.historical_match_id
        ),
        None,
    )
    resolved_facts = list(
        dict.fromkeys(
            _resolve_current_fact(candidate.candidate.item, reference)
            for reference in assessment.material_change_refs
        )
    )
    return HistoricalContext(
        status=status,
        historical_match_id=(
            matched.story.history_id if matched is not None else None
        ),
        prior_report_date_range=(
            matched.story.report_date_range.model_copy(deep=True)
            if matched is not None
            else None
        ),
        prior_title=matched.story.item.title if matched is not None else None,
        material_change_facts=resolved_facts,
    )


def _resolve_semantic_duplicates(
    scored: list[_ScoredCandidate],
) -> list[_ScoredCandidate]:
    """Resolve connected duplicate groups with one deterministic winner each."""
    groups = [
        {candidate.candidate.candidate_id} for candidate in scored
    ]
    active_ids = {
        candidate.candidate.candidate_id for candidate in scored
    }
    for candidate in scored:
        duplicate_id = candidate.assessment.semantic_duplicate_of
        if duplicate_id is None or duplicate_id not in active_ids:
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
        source.source_type.casefold() in PRIMARY_EVIDENCE_SOURCE_TYPES
        and (
            source.fact_support is None
            or (
                source.fact_support.summary
                and "event" in (source.evidence_roles or [])
            )
            or (
                item.published_date is not None
                and "event_date" in (source.evidence_roles or [])
            )
        )
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
