from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path

import pytest

from ai_weekly_agent.dates import raw_research_filename, weekly_report_filename
from ai_weekly_agent.history import (
    HISTORY_LOOKBACK_RUNS,
    MAX_HISTORY_CANDIDATES,
    historical_story_id,
    load_history,
    retrieve_historical_candidates,
)
from ai_weekly_agent.models import (
    CategoryResearchResult,
    CuratedItem,
    DateRange,
    FactSupport,
    HistoricalContext,
    HistoricalStory,
    NewsItem,
    ResearchRun,
    Source,
)
from ai_weekly_agent.report import (
    NO_BENCHMARK_INFORMATION,
    ReportContent,
    StoryExplanation,
    render_markdown as render_actual_report,
    save_report,
)
from ai_weekly_agent.research import save_research_run
from ai_weekly_agent.research import RESEARCH_CATEGORIES
from ai_weekly_agent.telemetry import (
    ApiUsageTotals,
    RunRecord,
    run_record_filename,
    save_run_record,
)
from ai_weekly_agent.verify import verify_research_run


CURRENT_RANGE = DateRange(start=date(2026, 9, 13), end=date(2026, 9, 19))
PAST_RANGE = DateRange(start=date(2026, 9, 6), end=date(2026, 9, 12))
CATEGORY = "AI model releases"


def make_item(
    title: str = "Example Lab releases Nova Engine",
    *,
    organization: str | None = "Example Lab",
    published_date: date | None = date(2026, 9, 10),
    category: str = CATEGORY,
    summary: str | None = None,
    url: str = "https://example.com/nova",
    detail: str = "Nova Engine uses a documented modular runtime.",
    benchmark_information: str | None = None,
) -> NewsItem:
    return NewsItem(
        title=title,
        category=category,
        organization=organization,
        published_date=published_date,
        summary=summary or f"Exact upstream summary for {title}.",
        technical_details=[detail],
        benchmark_information=benchmark_information,
        sources=[
            Source(
                title=f"Source for {title}",
                url=url,
                source_type="official",
            )
        ],
    )


def make_research_run(date_range: DateRange, *items: NewsItem) -> ResearchRun:
    return ResearchRun(
        date_range=date_range,
        categories=[CategoryResearchResult(category=CATEGORY, items=list(items))],
    )


def render_report(date_range: DateRange, items: list[NewsItem]) -> str:
    lines = [
        "# AI & Computer Engineering Weekly",
        "",
        f"**Week:** {date_range.start.isoformat()} — {date_range.end.isoformat()}",
        "",
        "## This Week at a Glance",
        "",
    ]
    if not items:
        lines.append("No stories passed the curation threshold for this period.")
        return "\n".join(lines) + "\n"

    lines.extend(["Placeholder overview.", "", "## Major Updates", ""])
    for position, item in enumerate(items, start=1):
        organization = item.organization or "Unknown / not specified"
        published = (
            item.published_date.isoformat()
            if item.published_date is not None
            else "Date not reliably established"
        )
        lines.extend(
            [
                f"### {position}. {item.title}",
                "",
                f"**Category:** {item.category}",
                f"**Organization:** {organization}",
                f"**Date:** {published}",
                "**Curation Score:** 4.00 / 5",
                "",
                "#### What happened?",
                "",
                item.summary,
                "",
                "#### Key technical details",
                "",
                *(f"- {detail}" for detail in item.technical_details),
                "",
                "#### What is it?",
                "",
                "Interpretive text is not used by history.",
                "",
                "#### Why does it matter?",
                "",
                "Interpretive text is not used by history.",
                "",
                "#### Performance / benchmarks",
                "",
                NO_BENCHMARK_INFORMATION,
                "",
                "#### What should I learn from this?",
                "",
                "Interpretive text is not used by history.",
                "",
                "#### Sources",
                "",
                *(
                    f"- [{source.title}]({source.url}) — {source.source_type}"
                    for source in item.sources
                ),
                "",
            ]
        )
    lines.extend(["## Source Index", "", "1. Placeholder index.", ""])
    return "\n".join(lines)


def artifact_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "data" / "runs",
        tmp_path / "data" / "raw",
        tmp_path / "reports",
    )


def write_run(
    tmp_path: Path,
    date_range: DateRange,
    *,
    raw_items: list[NewsItem] | None = None,
    report_items: list[NewsItem] | None = None,
    status: str = "success",
    record_name: str | None = None,
    raw_text: str | None = None,
    report_text: str | None = None,
    recorded_raw_path: Path | None = None,
    recorded_report_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    runs_dir, raw_dir, reports_dir = artifact_roots(tmp_path)
    for directory in (runs_dir, raw_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    items = raw_items if raw_items is not None else [make_item()]
    selected = report_items if report_items is not None else items
    raw_path = raw_dir / raw_research_filename(date_range)
    report_path = reports_dir / weekly_report_filename(date_range)
    raw_path.write_text(
        raw_text
        if raw_text is not None
        else make_research_run(date_range, *items).model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        report_text if report_text is not None else render_report(date_range, selected),
        encoding="utf-8",
    )

    finished_at = datetime.combine(date_range.end, datetime.min.time(), tzinfo=UTC)
    record = RunRecord(
        application_version="0.4.0",
        date_range=date_range,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
        status=status,
        error_stage="research" if status == "failed" else None,
        api_totals=ApiUsageTotals(
            logical_call_count=0,
            successful_call_count=0,
            failed_call_count=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            usage_complete=True,
        ),
        raw_research_path=recorded_raw_path or raw_path,
        report_path=recorded_report_path or report_path,
    )
    run_path = runs_dir / (record_name or run_record_filename(date_range))
    run_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return run_path, raw_path, report_path


def load_from(tmp_path: Path, current: DateRange = CURRENT_RANGE):
    runs_dir, raw_dir, reports_dir = artifact_roots(tmp_path)
    return load_history(
        current,
        runs_dir=runs_dir,
        raw_dir=raw_dir,
        reports_dir=reports_dir,
    )


def make_historical_story(
    title: str,
    *,
    date_range: DateRange = PAST_RANGE,
    position: int = 1,
    organization: str | None = "Example Lab",
    published_date: date | None = date(2026, 9, 10),
    url: str = "https://example.com/nova",
) -> HistoricalStory:
    return HistoricalStory(
        history_id=historical_story_id(date_range, position),
        report_date_range=date_range,
        report_position=position,
        item=make_item(
            title,
            organization=organization,
            published_date=published_date,
            url=url,
        ),
    )


def diagnostic_codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_missing_history_roots_are_unavailable(tmp_path: Path) -> None:
    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert result.runs_loaded == 0
    assert diagnostic_codes(result) == {"missing_runs_root"}


def test_no_prior_runs_is_unavailable_without_false_problem(
    tmp_path: Path,
) -> None:
    artifact_roots(tmp_path)[0].mkdir(parents=True)

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.diagnostics == ()


def test_only_successful_runs_are_used(tmp_path: Path) -> None:
    successful = make_item("Successful story", url="https://example.com/success")
    failed = make_item("Failed story", url="https://example.com/failed")
    write_run(tmp_path, PAST_RANGE, raw_items=[successful])
    failed_range = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    write_run(tmp_path, failed_range, raw_items=[failed], status="failed")

    result = load_from(tmp_path)

    assert result.state == "complete"
    assert [story.item.title for story in result.stories] == ["Successful story"]


def test_same_range_and_future_windows_are_excluded(tmp_path: Path) -> None:
    write_run(tmp_path, CURRENT_RANGE, raw_items=[make_item("Same range")])
    future = DateRange(start=date(2026, 9, 20), end=date(2026, 9, 26))
    write_run(tmp_path, future, raw_items=[make_item("Future range")])

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.diagnostics == ()


def test_overlapping_earlier_window_is_eligible(tmp_path: Path) -> None:
    overlap = DateRange(start=date(2026, 9, 10), end=date(2026, 9, 18))
    write_run(tmp_path, overlap, raw_items=[make_item("Earlier overlap")])

    result = load_from(tmp_path)

    assert result.state == "complete"
    assert result.stories[0].item.title == "Earlier overlap"


def test_runs_are_newest_first_and_capped_at_four(tmp_path: Path) -> None:
    current = DateRange(start=date(2026, 10, 25), end=date(2026, 10, 31))
    ranges = [
        DateRange(
            start=date(2026, 9, 13) + timedelta(days=7 * index),
            end=date(2026, 9, 19) + timedelta(days=7 * index),
        )
        for index in range(5)
    ]
    for index, date_range in enumerate(ranges):
        write_run(
            tmp_path,
            date_range,
            raw_items=[make_item(
                f"Story {index}", url=f"https://example.com/{index}"
            )],
        )

    result = load_from(tmp_path, current)

    assert HISTORY_LOOKBACK_RUNS == 4
    assert result.runs_loaded == 4
    assert [story.item.title for story in result.stories] == [
        "Story 4", "Story 3", "Story 2", "Story 1",
    ]


@pytest.mark.parametrize(
    ("missing_kind", "expected_code"),
    [
        ("raw", "missing_raw_artifact"),
        ("report", "missing_report_artifact"),
    ],
)
def test_missing_artifact_is_partial_when_other_history_survives(
    missing_kind: str, expected_code: str, tmp_path: Path,
) -> None:
    write_run(tmp_path, PAST_RANGE, raw_items=[make_item("Usable")])
    broken_range = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    _, raw_path, report_path = write_run(
        tmp_path, broken_range, raw_items=[make_item("Broken")]
    )
    (raw_path if missing_kind == "raw" else report_path).unlink()

    result = load_from(tmp_path)

    assert result.state == "partial"
    assert [story.item.title for story in result.stories] == ["Usable"]
    assert expected_code in diagnostic_codes(result)


def test_malformed_run_record_is_partial_with_usable_history(
    tmp_path: Path,
) -> None:
    write_run(tmp_path, PAST_RANGE, raw_items=[make_item("Usable")])
    runs_dir = artifact_roots(tmp_path)[0]
    (runs_dir / "malformed.json").write_text("{not json", encoding="utf-8")

    result = load_from(tmp_path)

    assert result.state == "partial"
    assert "malformed_run_record" in diagnostic_codes(result)


@pytest.mark.parametrize(
    ("artifact", "expected_code"),
    [
        ("raw", "malformed_raw_artifact"),
        ("report", "malformed_report_artifact"),
    ],
)
def test_malformed_artifact_makes_history_unavailable(
    artifact: str, expected_code: str, tmp_path: Path,
) -> None:
    _, raw_path, report_path = write_run(tmp_path, PAST_RANGE)
    target = raw_path if artifact == "raw" else report_path
    target.write_text("not a supported artifact", encoding="utf-8")

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert expected_code in diagnostic_codes(result)


@pytest.mark.parametrize("artifact", ["raw", "report"])
def test_recorded_artifact_path_cannot_escape_configured_root(
    artifact: str, tmp_path: Path,
) -> None:
    escaped = tmp_path / "outside.json"
    escaped.write_text("sensitive local file", encoding="utf-8")
    kwargs = {
        "recorded_raw_path": escaped if artifact == "raw" else None,
        "recorded_report_path": escaped if artifact == "report" else None,
    }
    write_run(tmp_path, PAST_RANGE, **kwargs)

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert f"unsafe_{artifact}_path" in diagnostic_codes(result)
    assert escaped.read_text(encoding="utf-8") == "sensitive local file"


@pytest.mark.parametrize("mismatch", ["raw", "report"])
def test_run_record_and_artifact_range_mismatch_is_rejected(
    mismatch: str, tmp_path: Path,
) -> None:
    _, raw_path, report_path = write_run(tmp_path, PAST_RANGE)
    other = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    if mismatch == "raw":
        raw_path.write_text(
            make_research_run(other, make_item()).model_dump_json(),
            encoding="utf-8",
        )
    else:
        report_path.write_text(render_report(other, [make_item()]), encoding="utf-8")

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert "range_mismatch" in diagnostic_codes(result)


def test_orphan_raw_and_report_are_not_treated_as_history(tmp_path: Path) -> None:
    _, raw_dir, reports_dir = artifact_roots(tmp_path)
    raw_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    raw_dir.joinpath(raw_research_filename(PAST_RANGE)).write_text(
        make_research_run(PAST_RANGE, make_item()).model_dump_json(),
        encoding="utf-8",
    )
    reports_dir.joinpath(weekly_report_filename(PAST_RANGE)).write_text(
        render_report(PAST_RANGE, [make_item()]), encoding="utf-8"
    )
    artifact_roots(tmp_path)[0].mkdir(parents=True)

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()


def test_duplicate_successful_records_for_one_range_are_ambiguous(
    tmp_path: Path,
) -> None:
    canonical, _, _ = write_run(tmp_path, PAST_RANGE)
    duplicate = canonical.with_name("duplicate.json")
    duplicate.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert "duplicate_run_record" in diagnostic_codes(result)


def test_unique_reconciliation_preserves_exact_raw_facts_and_files(
    tmp_path: Path,
) -> None:
    item = make_item(
        "Exact title",
        summary="Exact summary with capitalization and punctuation.",
        detail="Exact detail text.",
    )
    run_path, raw_path, report_path = write_run(tmp_path, PAST_RANGE, raw_items=[item])
    snapshots = {
        path: path.read_bytes() for path in (run_path, raw_path, report_path)
    }

    first = load_from(tmp_path)
    second = load_from(tmp_path)

    assert first == second
    assert first.state == "complete"
    assert len(first.stories) == 1
    assert first.stories[0].item.model_dump(mode="json") == item.model_dump(
        mode="json"
    )
    assert first.stories[0].item is not item
    assert {path: path.read_bytes() for path in snapshots} == snapshots


def test_zero_reconciliation_match_is_skipped(tmp_path: Path) -> None:
    raw = make_item("Raw story", url="https://example.com/raw")
    report = make_item("Different story", url="https://example.com/report")
    write_run(tmp_path, PAST_RANGE, raw_items=[raw], report_items=[report])

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert "unusable_report_story" in diagnostic_codes(result)


def test_unique_mutable_url_cannot_reconcile_incompatible_report_story(
    tmp_path: Path,
) -> None:
    shared_url = "https://example.com/products/nova"
    raw = make_item(
        "Nova Model A launch",
        summary="Example Lab launched Model A for embedded inference.",
        url=shared_url,
    )
    report = make_item(
        "Nova compiler toolchain update",
        summary="Example Lab released a compiler update for a different event.",
        url=shared_url,
    )
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[raw],
        report_items=[report],
    )

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert "unusable_report_story" in diagnostic_codes(result)


def test_raw_only_technical_fact_cannot_enter_reconstructed_history(
    tmp_path: Path,
) -> None:
    raw = make_item(
        "Matching published identity",
        detail="Raw-only technical fact that was not published.",
    )
    report = make_item(
        "Matching published identity",
        detail="Different technical fact shown in the report.",
    )
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[raw],
        report_items=[report],
    )

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert "unusable_report_story" in diagnostic_codes(result)


def test_ambiguous_reconciliation_match_is_skipped(tmp_path: Path) -> None:
    first = make_item("Duplicated story")
    second = first.model_copy(deep=True)
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[first, second],
        report_items=[first],
    )

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert any("multiple unique raw match" in d.message for d in result.diagnostics)


def test_multiple_report_stories_keep_deterministic_ordinals(tmp_path: Path) -> None:
    first = make_item("First story", url="https://example.com/first")
    second = make_item("Second story", url="https://example.com/second")
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[second, first],
        report_items=[first, second],
    )

    result = load_from(tmp_path)

    assert [story.item.title for story in result.stories] == [
        "First story", "Second story",
    ]
    assert [story.report_position for story in result.stories] == [1, 2]
    assert [story.history_id for story in result.stories] == [
        "history_2026-09-06_to_2026-09-12_story_001",
        "history_2026-09-06_to_2026-09-12_story_002",
    ]


def test_legacy_source_shape_reconciles_without_current_strict_verify(
    tmp_path: Path,
) -> None:
    item = make_item("Legacy covered story")
    payload = make_research_run(PAST_RANGE, item).model_dump(mode="json")
    source = payload["categories"][0]["items"][0]["sources"][0]
    source.pop("evidence_roles")
    source.pop("fact_support")
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[item],
        report_items=[item],
        raw_text=json.dumps(payload),
    )

    result = load_from(tmp_path)

    assert result.state == "complete"
    assert result.stories[0].item.sources[0].evidence_roles is None
    assert result.stories[0].item.sources[0].fact_support is None


def test_unsupported_legacy_raw_shape_is_skipped(tmp_path: Path) -> None:
    item = make_item("Unsupported legacy story")
    payload = make_research_run(PAST_RANGE, item).model_dump(mode="json")
    payload["categories"][0]["items"][0].pop("sources")
    write_run(tmp_path, PAST_RANGE, raw_text=json.dumps(payload), report_items=[item])

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert "malformed_raw_artifact" in diagnostic_codes(result)


def test_partially_reconciled_report_returns_partial_history(tmp_path: Path) -> None:
    usable = make_item("Usable story", url="https://example.com/usable")
    absent = make_item("Absent story", url="https://example.com/absent")
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[usable],
        report_items=[usable, absent],
    )

    result = load_from(tmp_path)

    assert result.state == "partial"
    assert [story.item.title for story in result.stories] == ["Usable story"]
    assert result.skipped_count == 1


def test_one_malformed_story_can_leave_other_history_usable(tmp_path: Path) -> None:
    first = make_item("Malformed story", url="https://example.com/bad")
    second = make_item("Usable story", url="https://example.com/good")
    report = render_report(PAST_RANGE, [first, second]).replace(
        "#### Sources", "#### Missing sources", 1
    )
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[first, second],
        report_text=report,
    )

    result = load_from(tmp_path)

    assert result.state == "partial"
    assert [story.item.title for story in result.stories] == ["Usable story"]


def test_valid_empty_report_does_not_invent_history(tmp_path: Path) -> None:
    write_run(tmp_path, PAST_RANGE, raw_items=[], report_items=[])

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("empty_reason", "expected_message"),
    [
        (
            "no_prepared_candidates",
            "No candidates were available for curation after deterministic "
            "preparation.",
        ),
        (
            "no_selection",
            "Candidates were assessed, but no story passed the existing "
            "curation and selection rules for this period.",
        ),
        (
            "all_repeats",
            "All assessed candidates repeated previously covered events, so "
            "no stories were selected for this period.",
        ),
    ],
)
def test_new_deterministic_empty_reports_remain_valid_history_artifacts(
    empty_reason: str, expected_message: str, tmp_path: Path
) -> None:
    report = render_actual_report(
        PAST_RANGE,
        [],
        empty_reason=empty_reason,
    )
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[],
        report_text=report,
    )

    result = load_from(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert result.diagnostics == ()
    assert expected_message in report


def test_actual_historical_markdown_round_trips_through_three_artifacts(
    tmp_path: Path,
) -> None:
    selected_new = make_item(
        "Selected local new story",
        url="https://example.com/selected-new",
    )
    selected_follow_up = make_item(
        "Selected follow-up story",
        url="https://example.com/selected-follow-up",
        detail="Exact current follow-up fact.",
        benchmark_information=(
            "Sanitized paper-reported throughput improved under the documented "
            "test setup."
        ),
    )
    selected_uncertain = make_item(
        "Selected uncertain story",
        url="https://example.com/selected-uncertain",
    )
    unselected = make_item(
        "Unselected raw candidate",
        url="https://example.com/unselected",
    )
    raw_run = make_research_run(
        PAST_RANGE,
        selected_new,
        selected_follow_up,
        selected_uncertain,
        unselected,
    )
    earlier_range = DateRange(
        start=date(2026, 8, 30), end=date(2026, 9, 5)
    )
    curated = [
        CuratedItem(
            item=selected_new,
            final_score=4.5,
            historical_context=HistoricalContext(status="NEW"),
        ),
        CuratedItem(
            item=selected_follow_up,
            final_score=4.25,
            historical_context=HistoricalContext(
                status="FOLLOW_UP",
                historical_match_id="history_prior_story_001",
                prior_report_date_range=earlier_range,
                prior_title="Earlier API preview",
                material_change_facts=["Exact current follow-up fact."],
            ),
        ),
        CuratedItem(
            item=selected_uncertain,
            final_score=4.0,
            historical_context=HistoricalContext(
                status="UNCERTAIN",
                historical_match_id="history_prior_story_002",
                prior_report_date_range=earlier_range,
                prior_title="Earlier related announcement",
            ),
        ),
    ]
    content = ReportContent(
        story_explanations=[
            StoryExplanation(
                story_id=f"story_{index:03d}",
                what_it_is=f"Interpretation {index}.",
                why_it_matters=f"Importance {index}.",
                student_takeaway=f"Guidance {index}.",
            )
            for index in range(1, 4)
        ]
    )
    runs_dir, raw_dir, reports_dir = artifact_roots(tmp_path)
    raw_path = save_research_run(raw_run, output_dir=raw_dir)
    markdown = render_actual_report(PAST_RANGE, curated, content)
    report_path = save_report(
        PAST_RANGE,
        markdown,
        output_dir=reports_dir,
    )
    finished_at = datetime(2026, 9, 13, tzinfo=UTC)
    record = RunRecord(
        application_version="0.4.0",
        date_range=PAST_RANGE,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
        status="success",
        api_totals=ApiUsageTotals(
            logical_call_count=0,
            successful_call_count=0,
            failed_call_count=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            usage_complete=True,
        ),
        raw_research_path=raw_path,
        report_path=report_path,
        run_record_path=runs_dir / run_record_filename(PAST_RANGE),
    )
    run_path = save_run_record(record, output_dir=runs_dir)
    snapshots = {
        path: path.read_bytes() for path in (run_path, raw_path, report_path)
    }

    result = load_history(
        CURRENT_RANGE,
        runs_dir=runs_dir,
        raw_dir=raw_dir,
        reports_dir=reports_dir,
    )

    assert result.state == "complete"
    assert [story.report_position for story in result.stories] == [1, 2, 3]
    assert [story.item.title for story in result.stories] == [
        selected_new.title,
        selected_follow_up.title,
        selected_uncertain.title,
    ]
    assert [story.item.model_dump(mode="json") for story in result.stories] == [
        item.model_dump(mode="json")
        for item in (selected_new, selected_follow_up, selected_uncertain)
    ]
    assert unselected.title not in {story.item.title for story in result.stories}
    assert markdown.count("#### Historical continuity") == 3
    assert markdown.count("### 1. ") == 1
    assert markdown.count("### 2. ") == 1
    assert markdown.count("### 3. ") == 1
    assert (
        "**Status:** New within the usable local report history loaded for "
        "this run.\n\n"
        "This local classification does not establish global novelty."
    ) in markdown
    assert (
        "**Status:** Follow-up to a previously reported development.\n\n"
        "**Prior report:** 2026-08-30 — 2026-09-05 — Earlier API preview\n\n"
        "**Current development identified for comparison:**\n\n"
        "- Exact current follow-up fact."
    ) in markdown
    assert (
        "**Status:** Historical continuity uncertain.\n\n"
        "**Compared with prior report:** 2026-08-30 — 2026-09-05 — "
        "Earlier related announcement\n\n"
        "Continuity could not be reliably established from the available "
        "local historical information. This does not mean current source "
        "verification failed."
    ) in markdown
    for position, item in enumerate(
        (selected_new, selected_follow_up, selected_uncertain), start=1
    ):
        story_tail = markdown.split(
            f"### {position}. {item.title}", 1
        )[1]
        what_happened = story_tail.split("#### What happened?\n\n", 1)[1].split(
            "\n\n#### Historical continuity", 1
        )[0]
        assert what_happened == item.summary
    assert "historical_match_id" not in markdown
    assert "https://example.com/unselected" not in markdown
    for published_fact in (
        selected_follow_up.summary,
        *selected_follow_up.technical_details,
        selected_follow_up.benchmark_information,
        selected_follow_up.sources[0].url,
    ):
        assert published_fact is not None
        assert published_fact in markdown
    assert {path: path.read_bytes() for path in snapshots} == snapshots


def test_actual_no_history_report_remains_loadable(tmp_path: Path) -> None:
    item = make_item("Legacy no-history rendered story")
    raw_run = make_research_run(PAST_RANGE, item)
    content = ReportContent(
        story_explanations=[
            StoryExplanation(
                story_id="story_001",
                what_it_is="Interpretation.",
                why_it_matters="Importance.",
                student_takeaway="Guidance.",
            )
        ]
    )
    report = render_actual_report(
        PAST_RANGE,
        [CuratedItem(item=item, final_score=4.0)],
        content,
    )
    write_run(
        tmp_path,
        PAST_RANGE,
        raw_items=[item],
        report_text=report,
        raw_text=raw_run.model_dump_json(),
    )

    result = load_from(tmp_path)

    assert result.state == "complete"
    assert [story.item for story in result.stories] == [item]
    assert "#### Historical continuity" not in report


def test_strict_source_filtering_round_trips_original_raw_artifact(
    tmp_path: Path,
) -> None:
    supported = Source(
        title="Sanitized primary source",
        url="https://EXAMPLE.com/filtered-story/#announcement",
        source_type="official",
        evidence_roles=["event", "event_date", "technical"],
        fact_support=FactSupport(
            summary=True,
            technical_detail_indices=[0],
            benchmark=False,
        ),
    )
    background = Source(
        title="Sanitized background source",
        url="https://example.com/filtered-story/background",
        source_type="official",
        evidence_roles=["background"],
        fact_support=FactSupport(
            summary=False,
            technical_detail_indices=[],
            benchmark=False,
        ),
    )
    removed = Source(
        title="Unusable source removed by Verify",
        url="not-a-usable-url",
        source_type="official",
        evidence_roles=["background"],
        fact_support=FactSupport(
            summary=False,
            technical_detail_indices=[],
            benchmark=False,
        ),
    )
    raw_item = make_item("Sanitized filtered-source story").model_copy(
        update={"sources": [supported, background, removed]},
        deep=True,
    )
    original_run = ResearchRun(
        date_range=PAST_RANGE,
        categories=[
            CategoryResearchResult(
                category=category,
                items=[raw_item] if category == CATEGORY else [],
            )
            for category in RESEARCH_CATEGORIES
        ],
    )

    verification = verify_research_run(
        original_run,
        require_provenance=True,
    )
    accepted = verification.accepted_run.categories[0].items[0]
    assert verification.rejected_item_ids == []
    assert [source.url for source in accepted.sources] == [
        "https://example.com/filtered-story",
        "https://example.com/filtered-story/background",
    ]

    runs_dir, raw_dir, reports_dir = artifact_roots(tmp_path)
    raw_path = save_research_run(original_run, output_dir=raw_dir)
    content = ReportContent(
        story_explanations=[
            StoryExplanation(
                story_id="story_001",
                what_it_is="Sanitized interpretation.",
                why_it_matters="Sanitized importance.",
                student_takeaway="Sanitized guidance.",
            )
        ]
    )
    markdown = render_actual_report(
        PAST_RANGE,
        [CuratedItem(item=accepted, final_score=4.0)],
        content,
    )
    report_path = save_report(PAST_RANGE, markdown, output_dir=reports_dir)
    finished_at = datetime(2026, 9, 13, tzinfo=UTC)
    record = RunRecord(
        application_version="0.4.0",
        date_range=PAST_RANGE,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
        status="success",
        api_totals=ApiUsageTotals(
            logical_call_count=0,
            successful_call_count=0,
            failed_call_count=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            usage_complete=True,
        ),
        raw_research_path=raw_path,
        report_path=report_path,
    )
    save_run_record(record, output_dir=runs_dir)

    loaded = load_history(
        CURRENT_RANGE,
        runs_dir=runs_dir,
        raw_dir=raw_dir,
        reports_dir=reports_dir,
    )

    assert loaded.state == "complete"
    assert len(loaded.stories) == 1
    assert loaded.stories[0].item == raw_item
    assert "not-a-usable-url" not in markdown


def test_historical_story_id_is_stable_and_rejects_nonpositive_position() -> None:
    assert historical_story_id(PAST_RANGE, 7) == (
        "history_2026-09-06_to_2026-09-12_story_007"
    )
    assert historical_story_id(PAST_RANGE, 7) == historical_story_id(PAST_RANGE, 7)
    with pytest.raises(ValueError, match="must be positive"):
        historical_story_id(PAST_RANGE, 0)


def test_shared_normalized_source_url_retrieves_candidate() -> None:
    historical = make_historical_story(
        "Alpha compiler preview", url="https://EXAMPLE.com/nova/#announcement"
    )
    current = make_item(
        "Beta runtime availability", url="https://example.com/nova"
    )

    matches = retrieve_historical_candidates(current, [historical])

    assert len(matches) == 1
    assert matches[0].match_reasons == ["shared_source_url"]


def test_exact_title_requires_compatible_nonempty_organization_and_date() -> None:
    historical = make_historical_story(
        "Same exact title", url="https://example.com/old"
    )
    current = make_item(
        " same exact title! ", url="https://example.com/new"
    )

    matches = retrieve_historical_candidates(current, [historical])

    assert [
        reason
        for reason in matches[0].match_reasons
        if reason == "exact_title"
    ] == ["exact_title"]


def test_organization_and_multiple_distinctive_title_terms_retrieve() -> None:
    historical = make_historical_story(
        "Nova Engine developer preview announced",
        url="https://example.com/preview",
    )
    current = make_item(
        "Nova Engine API becomes generally available",
        url="https://example.com/ga",
    )

    matches = retrieve_historical_candidates(current, [historical])

    assert matches[0].match_reasons == ["organization_title_terms"]


def test_organization_only_never_retrieves_same_company_different_product() -> None:
    historical = make_historical_story(
        "Company X releases Model A",
        organization="Company X",
        url="https://example.com/model-a",
    )
    current = make_item(
        "Company X releases Model B",
        organization="Company X",
        url="https://example.com/model-b",
    )

    assert retrieve_historical_candidates(current, [historical]) == []


def test_related_api_event_is_only_retrieved_not_semantically_classified() -> None:
    historical = make_historical_story(
        "Model X announced", url="https://example.com/model-x"
    )
    current = make_item(
        "Model X API becomes generally available",
        url="https://EXAMPLE.com/model-x/#api",
    )

    matches = retrieve_historical_candidates(current, [historical])

    assert len(matches) == 1
    assert set(type(matches[0]).model_fields) == {"story", "match_reasons"}
    assert "shared_source_url" in matches[0].match_reasons


def test_candidate_order_prefers_strongest_then_newest_and_caps_three() -> None:
    current = make_item(
        "Nova Engine launch",
        url="https://example.com/current",
    )
    ranges = [
        DateRange(start=date(2026, 8, 2), end=date(2026, 8, 8)),
        DateRange(start=date(2026, 8, 9), end=date(2026, 8, 15)),
        DateRange(start=date(2026, 8, 16), end=date(2026, 8, 22)),
        DateRange(start=date(2026, 8, 23), end=date(2026, 8, 29)),
        DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5)),
    ]
    stories = [
        make_historical_story(
            "Nova Engine launch",
            date_range=ranges[0], position=1,
            url="https://example.com/current",
        ),
        *(
            make_historical_story(
                f"Nova Engine update {index}",
                date_range=date_range,
                position=index,
                url=f"https://example.com/update-{index}",
            )
            for index, date_range in enumerate(ranges[1:], start=2)
        ),
    ]

    first = retrieve_historical_candidates(current, stories)
    second = retrieve_historical_candidates(current, list(reversed(stories)))

    assert MAX_HISTORY_CANDIDATES == 3
    assert len(first) == 3
    assert first == second
    assert first[0].story is stories[0]
    assert [match.story.report_date_range for match in first[1:]] == [
        ranges[4], ranges[3],
    ]


def test_candidate_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        retrieve_historical_candidates(make_item(), [], limit=0)


def test_lookback_must_be_positive(tmp_path: Path) -> None:
    runs_dir, raw_dir, reports_dir = artifact_roots(tmp_path)
    with pytest.raises(ValueError, match="lookback_runs must be positive"):
        load_history(
            CURRENT_RANGE,
            runs_dir=runs_dir,
            raw_dir=raw_dir,
            reports_dir=reports_dir,
            lookback_runs=0,
        )


def test_old_schema_v1_run_record_without_research_categories_still_parses(
    tmp_path: Path,
) -> None:
    run_path, _, _ = write_run(tmp_path, PAST_RANGE)
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    for call in payload["api_calls"]:
        call.pop("research_category", None)

    restored = RunRecord.model_validate(payload)

    assert restored.schema_version == 1


def test_loader_does_not_mutate_input_model_objects() -> None:
    current = make_item("Nova Engine current")
    historical = make_historical_story("Nova Engine historical")
    current_snapshot = deepcopy(current.model_dump(mode="python"))
    historical_snapshot = deepcopy(historical.model_dump(mode="python"))

    retrieve_historical_candidates(current, [historical])

    assert current.model_dump(mode="python") == current_snapshot
    assert historical.model_dump(mode="python") == historical_snapshot
