"""Read-only reconstruction and deterministic retrieval of local history."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Literal

from pydantic import ValidationError

from ai_weekly_agent.dates import raw_research_filename, weekly_report_filename
from ai_weekly_agent.models import (
    DateRange,
    HistoricalMatch,
    HistoricalMatchReason,
    HistoricalStory,
    NewsItem,
    ResearchRun,
)
from ai_weekly_agent.research import normalize_source_url
from ai_weekly_agent.report import NO_BENCHMARK_INFORMATION, NO_TECHNICAL_DETAILS
from ai_weekly_agent.telemetry import RunRecord, run_record_filename


HISTORY_LOOKBACK_RUNS = 4
MAX_HISTORY_CANDIDATES = 3

HistoryLoadState = Literal["complete", "partial", "unavailable"]

_REPORT_TITLE = "# AI & Computer Engineering Weekly"
_EMPTY_REPORT_TEXTS = (
    "No stories passed the curation threshold for this period.",
    "No candidates were available for curation after deterministic preparation.",
    "Candidates were assessed, but no story passed the existing curation and "
    "selection rules for this period.",
    "All assessed candidates repeated previously covered events, so no stories "
    "were selected for this period.",
)
_UNKNOWN_ORGANIZATION = "Unknown / not specified"
_UNKNOWN_DATE = "Date not reliably established"
_WEEK_RE = re.compile(
    r"^\*\*Week:\*\*\s+(\d{4}-\d{2}-\d{2})\s+[—-]\s+"
    r"(\d{4}-\d{2}-\d{2})\s*$"
)
_STORY_RE = re.compile(r"^###\s+(\d+)\.\s+(.+?)\s*$")
_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+-]*", re.IGNORECASE)
_TITLE_PUNCTUATION = " \t\r\n.,!?;:'\"()[]{}<>-–—"
_GENERIC_TITLE_TERMS = frozenset(
    {
        "announced",
        "announcement",
        "available",
        "becomes",
        "company",
        "general",
        "generally",
        "launch",
        "launched",
        "model",
        "models",
        "platform",
        "release",
        "released",
        "releases",
        "system",
        "systems",
        "update",
        "updated",
    }
)
_MATCH_REASON_ORDER: tuple[HistoricalMatchReason, ...] = (
    "shared_source_url",
    "exact_title",
    "organization_title_terms",
)


@dataclass(frozen=True)
class HistoryDiagnostic:
    """One concise, non-fatal problem with local historical data."""

    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class HistoryLoadResult:
    """Safely reconstructed history plus its completeness state."""

    state: HistoryLoadState
    stories: tuple[HistoricalStory, ...]
    diagnostics: tuple[HistoryDiagnostic, ...]
    runs_loaded: int
    skipped_count: int


@dataclass(frozen=True)
class _RenderedStory:
    position: int
    title: str
    category: str
    organization: str | None
    published_date: date | None
    summary: str
    technical_details_text: str
    benchmark_text: str
    source_urls: frozenset[str]


@dataclass(frozen=True)
class _ParsedReport:
    date_range: DateRange
    stories: tuple[_RenderedStory, ...]
    story_diagnostics: tuple[str, ...]


class _HistoryArtifactError(ValueError):
    """Raised for one expected malformed or unsafe history artifact."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_history(
    current_date_range: DateRange,
    *,
    runs_dir: str | Path = Path("data/runs"),
    raw_dir: str | Path = Path("data/raw"),
    reports_dir: str | Path = Path("reports"),
    lookback_runs: int = HISTORY_LOOKBACK_RUNS,
) -> HistoryLoadResult:
    """Reconstruct previously reported stories without mutating artifacts."""
    if lookback_runs <= 0:
        raise ValueError("lookback_runs must be positive")

    run_root = Path(runs_dir)
    raw_root = Path(raw_dir)
    report_root = Path(reports_dir)
    diagnostics: list[HistoryDiagnostic] = []
    skipped_count = 0

    if not run_root.is_dir():
        diagnostic = HistoryDiagnostic(
            code="missing_runs_root",
            message="Historical RunRecord directory is unavailable.",
            path=run_root,
        )
        return HistoryLoadResult(
            state="unavailable",
            stories=(),
            diagnostics=(diagnostic,),
            runs_loaded=0,
            skipped_count=1,
        )

    eligible: list[tuple[Path, RunRecord]] = []
    for path in sorted(run_root.glob("*.json")):
        try:
            record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            diagnostics.append(
                HistoryDiagnostic(
                    code="malformed_run_record",
                    message=(
                        "Could not parse historical RunRecord: "
                        f"{type(exc).__name__}."
                    ),
                    path=path,
                )
            )
            skipped_count += 1
            continue

        if record.status != "success":
            continue
        if record.date_range == current_date_range:
            continue
        if record.date_range.end >= current_date_range.end:
            continue
        eligible.append((path, record))

    by_range: dict[tuple[date, date], list[tuple[Path, RunRecord]]] = defaultdict(list)
    for entry in eligible:
        date_range = entry[1].date_range
        by_range[(date_range.start, date_range.end)].append(entry)

    unambiguous: list[tuple[Path, RunRecord]] = []
    for entries in by_range.values():
        if len(entries) > 1:
            diagnostics.append(
                HistoryDiagnostic(
                    code="duplicate_run_record",
                    message=(
                        "Multiple successful RunRecords describe one "
                        "historical range."
                    ),
                    path=min(path for path, _ in entries),
                )
            )
            skipped_count += len(entries)
            continue
        unambiguous.append(entries[0])

    unambiguous.sort(key=_run_sort_key)
    stories: list[HistoricalStory] = []
    runs_loaded = 0

    for run_path, record in unambiguous:
        if runs_loaded >= lookback_runs:
            break
        if run_path.name != run_record_filename(record.date_range):
            diagnostics.append(
                HistoryDiagnostic(
                    code="unexpected_run_filename",
                    message=(
                        "Historical RunRecord does not use its date-range "
                        "filename."
                    ),
                    path=run_path,
                )
            )
            skipped_count += 1
            continue

        try:
            run_stories, run_diagnostics = _load_run_stories(
                record,
                raw_root=raw_root,
                report_root=report_root,
            )
        except _HistoryArtifactError as exc:
            diagnostics.append(
                HistoryDiagnostic(
                    code=exc.code,
                    message=str(exc),
                    path=run_path,
                )
            )
            skipped_count += 1
            continue

        diagnostics.extend(run_diagnostics)
        skipped_count += len(run_diagnostics)
        if not run_stories:
            continue
        stories.extend(run_stories)
        runs_loaded += 1

    if not stories:
        state: HistoryLoadState = "unavailable"
    elif diagnostics:
        state = "partial"
    else:
        state = "complete"

    return HistoryLoadResult(
        state=state,
        stories=tuple(stories),
        diagnostics=tuple(diagnostics),
        runs_loaded=runs_loaded,
        skipped_count=skipped_count,
    )


def historical_story_id(date_range: DateRange, report_position: int) -> str:
    """Return the stable identity for one ordinal in one historical report."""
    if report_position < 1:
        raise ValueError("report_position must be positive")
    return (
        f"history_{date_range.start.isoformat()}_to_"
        f"{date_range.end.isoformat()}_story_{report_position:03d}"
    )


def retrieve_historical_candidates(
    current_item: NewsItem,
    stories: Sequence[HistoricalStory],
    *,
    limit: int = MAX_HISTORY_CANDIDATES,
) -> list[HistoricalMatch]:
    """Retrieve explainable history candidates without classifying them."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    matches: list[HistoricalMatch] = []
    for story in stories:
        reasons = _match_reasons(current_item, story.item)
        if reasons:
            matches.append(HistoricalMatch(story=story, match_reasons=reasons))

    matches.sort(key=_historical_match_sort_key)
    return matches[:limit]


def _run_sort_key(entry: tuple[Path, RunRecord]) -> tuple[int, int, float, str]:
    path, record = entry
    return (
        -record.date_range.end.toordinal(),
        -record.date_range.start.toordinal(),
        -record.finished_at.timestamp(),
        path.name,
    )


def _load_run_stories(
    record: RunRecord,
    *,
    raw_root: Path,
    report_root: Path,
) -> tuple[list[HistoricalStory], list[HistoryDiagnostic]]:
    raw_path = _artifact_path(
        record.raw_research_path,
        root=raw_root,
        expected_name=raw_research_filename(record.date_range),
        kind="raw",
    )
    report_path = _artifact_path(
        record.report_path,
        root=report_root,
        expected_name=weekly_report_filename(record.date_range),
        kind="report",
    )

    try:
        raw_text = raw_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _HistoryArtifactError(
            "missing_raw_artifact",
            f"Could not read historical raw ResearchRun: {type(exc).__name__}.",
        ) from exc
    try:
        research_run = ResearchRun.model_validate_json(raw_text)
    except ValidationError as exc:
        raise _HistoryArtifactError(
            "malformed_raw_artifact",
            "Historical raw ResearchRun is malformed or unsupported.",
        ) from exc

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _HistoryArtifactError(
            "missing_report_artifact",
            f"Could not read historical report: {type(exc).__name__}.",
        ) from exc

    if research_run.date_range != record.date_range:
        raise _HistoryArtifactError(
            "range_mismatch",
            "RunRecord and raw ResearchRun date ranges do not match.",
        )
    parsed_report = _parse_report(report_text)
    if parsed_report.date_range != record.date_range:
        raise _HistoryArtifactError(
            "range_mismatch",
            "RunRecord and report date ranges do not match.",
        )

    stories, messages = _reconcile_report(research_run, parsed_report)
    diagnostics = [
        HistoryDiagnostic(
            code="unusable_report_story",
            message=message,
            path=report_path,
        )
        for message in (*parsed_report.story_diagnostics, *messages)
    ]
    return stories, diagnostics


def _artifact_path(
    recorded_path: Path | None,
    *,
    root: Path,
    expected_name: str,
    kind: Literal["raw", "report"],
) -> Path:
    if recorded_path is None:
        raise _HistoryArtifactError(
            f"missing_{kind}_path",
            f"Historical RunRecord has no {kind} artifact path.",
        )

    expected = (root / expected_name).resolve(strict=False)
    candidate = Path(recorded_path).resolve(strict=False)
    if candidate != expected:
        raise _HistoryArtifactError(
            f"unsafe_{kind}_path",
            f"Historical {kind} path is outside the expected artifact location.",
        )
    return expected


def _parse_report(markdown: str) -> _ParsedReport:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != _REPORT_TITLE:
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical report has an unsupported title or structure.",
        )

    week_matches = [match for line in lines if (match := _WEEK_RE.match(line))]
    if len(week_matches) != 1:
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical report must contain exactly one valid Week range.",
        )
    try:
        date_range = DateRange(
            start=date.fromisoformat(week_matches[0].group(1)),
            end=date.fromisoformat(week_matches[0].group(2)),
        )
    except ValueError as exc:
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical report Week range is invalid.",
        ) from exc

    try:
        major_index = lines.index("## Major Updates")
    except ValueError as exc:
        if any(
            empty_text in line
            for line in lines
            for empty_text in _EMPTY_REPORT_TEXTS
        ):
            return _ParsedReport(date_range, (), ())
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical report has no Major Updates section.",
        ) from exc

    section_end = next(
        (
            index
            for index in range(major_index + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    headings = [
        (index, match)
        for index in range(major_index + 1, section_end)
        if (match := _STORY_RE.match(lines[index]))
    ]
    if not headings:
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical Major Updates section contains no story headings.",
        )
    if [int(match.group(1)) for _, match in headings] != list(
        range(1, len(headings) + 1)
    ):
        raise _HistoryArtifactError(
            "malformed_report_artifact",
            "Historical report story ordinals are not contiguous and unique.",
        )

    stories: list[_RenderedStory] = []
    story_diagnostics: list[str] = []
    for heading_position, (start, match) in enumerate(headings):
        end = (
            headings[heading_position + 1][0]
            if heading_position + 1 < len(headings)
            else section_end
        )
        try:
            stories.append(
                _parse_story_block(
                    lines[start:end],
                    position=int(match.group(1)),
                    title=match.group(2).strip(),
                )
            )
        except _HistoryArtifactError as exc:
            story_diagnostics.append(
                f"Story {match.group(1)} was skipped: {exc}."
            )

    return _ParsedReport(
        date_range=date_range,
        stories=tuple(stories),
        story_diagnostics=tuple(story_diagnostics),
    )


def _parse_story_block(
    lines: list[str], *, position: int, title: str
) -> _RenderedStory:
    category = _metadata_value(lines, "Category")
    organization_text = _metadata_value(lines, "Organization")
    date_text = _metadata_value(lines, "Date")
    summary = _section_text(lines, "#### What happened?")
    technical_details_text = _section_text(
        lines, "#### Key technical details"
    )
    benchmark_text = _section_text(lines, "#### Performance / benchmarks")
    source_text = _section_text(lines, "#### Sources", allow_headings=True)
    source_urls = frozenset(
        normalized
        for match in _LINK_RE.finditer(source_text)
        if (normalized := normalize_source_url(match.group(1))) is not None
    )
    if not title or not category or not summary or not source_urls:
        raise _HistoryArtifactError(
            "malformed_report_story",
            "required title, category, summary, or source data is missing",
        )

    organization = (
        None if organization_text == _UNKNOWN_ORGANIZATION else organization_text
    )
    if date_text == _UNKNOWN_DATE:
        published_date = None
    else:
        try:
            published_date = date.fromisoformat(date_text)
        except ValueError as exc:
            raise _HistoryArtifactError(
                "malformed_report_story", "published date is invalid"
            ) from exc

    return _RenderedStory(
        position=position,
        title=title,
        category=category,
        organization=organization,
        published_date=published_date,
        summary=summary,
        technical_details_text=technical_details_text,
        benchmark_text=benchmark_text,
        source_urls=source_urls,
    )


def _metadata_value(lines: list[str], name: str) -> str:
    prefix = f"**{name}:** "
    values = [line[len(prefix):].strip() for line in lines if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        raise _HistoryArtifactError(
            "malformed_report_story", f"{name} metadata is missing or repeated"
        )
    return values[0]


def _section_text(
    lines: list[str], heading: str, *, allow_headings: bool = False
) -> str:
    try:
        start = lines.index(heading) + 1
    except ValueError as exc:
        raise _HistoryArtifactError(
            "malformed_report_story", f"{heading} section is missing"
        ) from exc
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("#### ")
        ),
        len(lines),
    )
    content = list(lines[start:end])
    while content and not content[0].strip():
        content.pop(0)
    while content and not content[-1].strip():
        content.pop()
    text = "\n".join(content).strip()
    if not text and not allow_headings:
        raise _HistoryArtifactError(
            "malformed_report_story", f"{heading} section is empty"
        )
    return text


def _reconcile_report(
    research_run: ResearchRun,
    report: _ParsedReport,
) -> tuple[list[HistoricalStory], list[str]]:
    raw_items = [
        item
        for category in research_run.categories
        for item in category.items
    ]
    used_indices: set[int] = set()
    stories: list[HistoricalStory] = []
    diagnostics: list[str] = []

    for rendered in report.stories:
        matches = [
            index
            for index, item in enumerate(raw_items)
            if _report_story_matches_item(rendered, item)
        ]
        if len(matches) != 1:
            outcome = "no" if not matches else "multiple"
            diagnostics.append(
                f"Story {rendered.position} had {outcome} unique raw match."
            )
            continue
        raw_index = matches[0]
        if raw_index in used_indices:
            diagnostics.append(
                f"Story {rendered.position} reused another story's raw match."
            )
            continue
        used_indices.add(raw_index)
        stories.append(
            HistoricalStory(
                history_id=historical_story_id(
                    report.date_range, rendered.position
                ),
                report_date_range=report.date_range.model_copy(deep=True),
                report_position=rendered.position,
                item=raw_items[raw_index].model_copy(deep=True),
            )
        )

    return stories, diagnostics


def _report_story_matches_item(rendered: _RenderedStory, item: NewsItem) -> bool:
    category_matches = _normalize_text(rendered.category) == _normalize_text(
        item.category
    )
    organization_matches = _normalize_optional_text(
        rendered.organization
    ) == _normalize_optional_text(item.organization)
    date_matches = rendered.published_date == item.published_date
    if not (category_matches and organization_matches and date_matches):
        return False

    title_matches = _normalize_title(rendered.title) == _normalize_title(item.title)
    summary_matches = _normalize_text(rendered.summary) == _normalize_text(item.summary)
    expected_technical_details = (
        "\n".join(f"- {detail}" for detail in item.technical_details)
        if item.technical_details
        else NO_TECHNICAL_DETAILS
    )
    technical_details_match = (
        rendered.technical_details_text == expected_technical_details
    )
    expected_benchmark = (
        item.benchmark_information
        if item.benchmark_information is not None
        else NO_BENCHMARK_INFORMATION
    )
    benchmark_matches = rendered.benchmark_text == expected_benchmark
    item_urls = {
        normalized
        for source in item.sources
        if (normalized := normalize_source_url(source.url)) is not None
    }
    sources_match = rendered.source_urls == item_urls
    # The deterministic renderer publishes these fields directly from the
    # selected item. Require the complete identity tuple so a unique mutable
    # product URL cannot attach an unrelated raw candidate to a report story.
    return (
        title_matches
        and summary_matches
        and technical_details_match
        and benchmark_matches
        and sources_match
    )


def _match_reasons(
    current: NewsItem, historical: NewsItem
) -> list[HistoricalMatchReason]:
    reasons: list[HistoricalMatchReason] = []
    current_urls = {
        normalized
        for source in current.sources
        if (normalized := normalize_source_url(source.url)) is not None
    }
    historical_urls = {
        normalized
        for source in historical.sources
        if (normalized := normalize_source_url(source.url)) is not None
    }
    if current_urls & historical_urls:
        reasons.append("shared_source_url")

    organization = _normalize_optional_text(current.organization)
    same_nonempty_organization = bool(
        organization
        and organization == _normalize_optional_text(historical.organization)
    )
    dates_compatible = (
        current.published_date is None
        or historical.published_date is None
        or current.published_date == historical.published_date
    )
    if (
        same_nonempty_organization
        and dates_compatible
        and _normalize_title(current.title) == _normalize_title(historical.title)
    ):
        reasons.append("exact_title")

    shared_terms = _distinctive_title_terms(current.title) & _distinctive_title_terms(
        historical.title
    )
    if same_nonempty_organization and len(shared_terms) >= 2:
        reasons.append("organization_title_terms")

    return reasons


def _historical_match_sort_key(
    match: HistoricalMatch,
) -> tuple[int, int, int, int, int, int, int, str]:
    reasons = set(match.match_reasons)
    story = match.story
    return (
        -int("shared_source_url" in reasons),
        -int("exact_title" in reasons),
        -int("organization_title_terms" in reasons),
        -len(reasons),
        -story.report_date_range.end.toordinal(),
        -story.report_date_range.start.toordinal(),
        story.report_position,
        story.history_id,
    )


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().strip(_TITLE_PUNCTUATION).split())


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_optional_text(value: str | None) -> str:
    return _normalize_text(value) if value else ""


def _distinctive_title_terms(value: str) -> set[str]:
    return {
        term.casefold()
        for term in _TOKEN_RE.findall(value)
        if len(term) >= 4 and term.casefold() not in _GENERIC_TITLE_TERMS
    }
