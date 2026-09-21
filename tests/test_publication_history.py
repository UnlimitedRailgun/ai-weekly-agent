from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

import ai_weekly_agent.main as main_module
from ai_weekly_agent.dates import raw_research_filename, weekly_report_filename
from ai_weekly_agent.history import (
    HISTORY_LOOKBACK_RUNS,
    check_legacy_publication,
    load_history,
    load_publication_history,
)
from ai_weekly_agent.models import (
    CategoryResearchResult,
    CuratedItem,
    DateRange,
    FactSupport,
    HistoricalContext,
    NewsItem,
    ResearchRun,
    Source,
)
from ai_weekly_agent.report import ReportContent, StoryExplanation, render_markdown
from ai_weekly_agent.research import RESEARCH_CATEGORIES
from ai_weekly_agent.storage import PublicationStorage
from ai_weekly_agent.telemetry import ApiUsageTotals, RunRecord, run_record_filename
from ai_weekly_agent.verify import verify_research_run


CURRENT = DateRange(start=date(2026, 9, 13), end=date(2026, 9, 19))
PAST = DateRange(start=date(2026, 9, 6), end=date(2026, 9, 12))
CATEGORY = "AI model releases"
PUBLISHED_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def item(
    title: str,
    date_range: DateRange = PAST,
    *,
    url: str | None = None,
    detail: str | None = None,
) -> NewsItem:
    return NewsItem(
        title=title,
        category=CATEGORY,
        organization="Example Lab",
        published_date=date_range.end,
        summary=f"Exact upstream summary for {title}.",
        technical_details=[detail or f"Exact technical detail for {title}."],
        benchmark_information=None,
        sources=[
            Source(
                title=f"Source for {title}",
                url=url or f"https://example.com/{title.casefold().replace(' ', '-')}",
                source_type="official",
            )
        ],
    )


def research_run(date_range: DateRange, items: list[NewsItem]) -> ResearchRun:
    return ResearchRun(
        date_range=date_range,
        categories=[CategoryResearchResult(category=CATEGORY, items=items)],
    )


def production_report(date_range: DateRange, items: list[NewsItem]) -> str:
    if not items:
        return render_markdown(date_range, [], empty_reason="no_selection")
    curated = [
        CuratedItem(
            item=news_item,
            final_score=4.0,
            historical_context=HistoricalContext(status="NEW"),
        )
        for news_item in items
    ]
    content = ReportContent(
        story_explanations=[
            StoryExplanation(
                story_id=f"story_{position:03d}",
                what_it_is="Local fixed explanation.",
                why_it_matters="Local fixed importance.",
                student_takeaway="Local fixed guidance.",
            )
            for position in range(1, len(items) + 1)
        ]
    )
    return render_markdown(date_range, curated, content)


def publish(
    storage: PublicationStorage,
    date_range: DateRange,
    items: list[NewsItem],
    *,
    run_id: str = "1" * 32,
    report_items: list[NewsItem] | None = None,
    overwrite: bool = False,
):
    with storage.acquire_lock(date_range) as lock:
        attempt = storage.allocate_attempt(
            date_range,
            lock=lock,
            run_id=run_id,
        )
        storage.write_raw(
            attempt,
            research_run(date_range, items),
            lock=lock,
        )
        storage.write_report(
            attempt,
            production_report(
                date_range,
                items if report_items is None else report_items,
            ),
            lock=lock,
        )
        result = storage.publish(
            attempt,
            application_version="0.5.0",
            lock=lock,
            overwrite=overwrite,
            published_at=PUBLISHED_AT,
        )
    return attempt, result.publication


def write_legacy(
    root: Path,
    date_range: DateRange,
    items: list[NewsItem],
    *,
    report_items: list[NewsItem] | None = None,
    name: str | None = None,
    relative_paths: bool = False,
) -> Path:
    runs = root / "data" / "runs"
    raw = root / "data" / "raw"
    reports = root / "reports"
    for directory in (runs, raw, reports):
        directory.mkdir(parents=True, exist_ok=True)
    raw_path = raw / raw_research_filename(date_range)
    report_path = reports / weekly_report_filename(date_range)
    raw_path.write_text(
        research_run(date_range, items).model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        production_report(
            date_range,
            items if report_items is None else report_items,
        ),
        encoding="utf-8",
    )
    finished_at = datetime.combine(date_range.end, datetime.min.time(), tzinfo=UTC)
    record = RunRecord(
        application_version="0.5.0",
        date_range=date_range,
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
        raw_research_path=(
            Path("data/raw") / raw_path.name if relative_paths else raw_path
        ),
        report_path=(
            Path("reports") / report_path.name
            if relative_paths
            else report_path
        ),
    )
    run_path = runs / (name or run_record_filename(date_range))
    run_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return run_path


def load(root: Path, current: DateRange = CURRENT, *, lookback_runs: int = 4):
    return load_publication_history(
        current,
        storage=PublicationStorage(root),
        lookback_runs=lookback_runs,
    )


def codes(result) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def rewrite_manifest_artifact_reference(
    manifest_path: Path,
    kind: str,
    content: bytes,
) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[kind]["sha256"] = hashlib.sha256(content).hexdigest()
    payload[kind]["byte_length"] = len(content)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_legacy_entry_remains_separate_after_main_adopts_mixed_loader(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    publish(storage, PAST, [item("Manifest story")])

    legacy = load_history(
        CURRENT,
        runs_dir=tmp_path / "data" / "runs",
        raw_dir=tmp_path / "data" / "raw",
        reports_dir=tmp_path / "reports",
    )
    mixed = load_publication_history(CURRENT, storage=storage)

    assert legacy.stories == ()
    assert [story.item.title for story in mixed.stories] == ["Manifest story"]
    assert main_module.load_publication_history is load_publication_history
    assert "load_history" not in main_module.__dict__


def test_valid_manifest_masks_same_range_legacy(tmp_path: Path) -> None:
    write_legacy(tmp_path, PAST, [item("Legacy story")])
    publish(PublicationStorage(tmp_path), PAST, [item("Manifest story")])

    result = load(tmp_path)

    assert result.state == "complete"
    assert result.runs_loaded == 1
    assert [story.item.title for story in result.stories] == ["Manifest story"]
    assert result.diagnostics == ()


def test_valid_manifest_masks_malformed_same_range_legacy(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    publish(storage, PAST, [item("Manifest story")])
    legacy = tmp_path / "data" / "runs" / run_record_filename(PAST)
    legacy.write_text("{broken legacy", encoding="utf-8")

    result = load(tmp_path)

    assert [story.item.title for story in result.stories] == ["Manifest story"]
    assert "malformed_run_record" not in codes(result)


def test_absent_manifest_uses_strict_legacy_path(tmp_path: Path) -> None:
    write_legacy(tmp_path, PAST, [item("Legacy story")])

    result = load(tmp_path)

    assert result.state == "complete"
    assert [story.item.title for story in result.stories] == ["Legacy story"]


def test_absent_manifest_preserves_legacy_duplicate_rejection(tmp_path: Path) -> None:
    canonical = write_legacy(tmp_path, PAST, [item("Ambiguous legacy")])
    duplicate = canonical.with_name("duplicate.json")
    duplicate.write_bytes(canonical.read_bytes())

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert codes(result) == ["duplicate_run_record"]
    assert result.skipped_count == 2


@pytest.mark.parametrize(
    "damage",
    ["malformed", "unsupported", "digest", "missing_artifact"],
)
def test_invalid_manifest_masks_valid_legacy(
    tmp_path: Path,
    damage: str,
) -> None:
    write_legacy(tmp_path, PAST, [item("Legacy must stay masked")])
    _, publication = publish(
        PublicationStorage(tmp_path),
        PAST,
        [item("Manifest story")],
    )
    if damage == "malformed":
        publication.manifest_path.write_text("{broken", encoding="utf-8")
    elif damage == "unsupported":
        payload = json.loads(publication.manifest_path.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        publication.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif damage == "digest":
        publication.raw_path.write_bytes(publication.raw_bytes + b"\n")
    else:
        publication.report_path.unlink()

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert codes(result) == ["invalid_publication"]
    assert result.skipped_count == 1


def test_empty_publication_masks_nonempty_legacy_and_seeks_older(
    tmp_path: Path,
) -> None:
    older = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    write_legacy(tmp_path, PAST, [item("Masked legacy")])
    write_legacy(tmp_path, older, [item("Older usable", older)])
    publish(PublicationStorage(tmp_path), PAST, [])

    result = load(tmp_path)

    assert result.state == "complete"
    assert result.runs_loaded == 1
    assert [story.item.title for story in result.stories] == ["Older usable"]
    assert result.diagnostics == ()


def test_only_valid_empty_publication_is_unavailable_without_damage(
    tmp_path: Path,
) -> None:
    write_legacy(tmp_path, PAST, [item("Masked legacy")])
    publish(PublicationStorage(tmp_path), PAST, [])

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert result.runs_loaded == 0
    assert result.stories == ()
    assert result.diagnostics == ()
    assert result.skipped_count == 0


def test_unpublished_attempt_and_nested_json_are_not_history(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    with storage.acquire_lock(PAST) as lock:
        attempt = storage.allocate_attempt(PAST, lock=lock, run_id="1" * 32)
        storage.write_raw(attempt, research_run(PAST, [item("Orphan")]), lock=lock)
        storage.write_report(
            attempt,
            production_report(PAST, [item("Orphan")]),
            lock=lock,
        )
        (attempt.attempt_dir / "run.json").write_text(
            "{failed telemetry fixture", encoding="utf-8"
        )

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert result.diagnostics == ()


def test_publication_needs_no_attempt_run_record(tmp_path: Path) -> None:
    publish(PublicationStorage(tmp_path), PAST, [item("Published story")])

    result = load(tmp_path)

    assert [story.item.title for story in result.stories] == ["Published story"]
    assert not list((tmp_path / "data" / "runs" / "attempts").rglob("run.json"))


@pytest.mark.parametrize("mismatch", ["raw", "report"])
def test_authenticated_content_range_mismatch_is_rejected(
    tmp_path: Path,
    mismatch: str,
) -> None:
    other = DateRange(start=date(2026, 8, 31), end=date(2026, 9, 6))
    _, publication = publish(
        PublicationStorage(tmp_path),
        PAST,
        [item("Published story")],
    )
    if mismatch == "raw":
        content = research_run(other, [item("Published story", other)]).model_dump_json().encode()
        publication.raw_path.write_bytes(content)
        rewrite_manifest_artifact_reference(publication.manifest_path, "raw", content)
    else:
        content = production_report(other, [item("Published story", other)]).encode()
        publication.report_path.write_bytes(content)
        rewrite_manifest_artifact_reference(publication.manifest_path, "report", content)

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert codes(result) == ["range_mismatch"]


def test_partial_story_failure_keeps_positions_without_legacy_supplement(
    tmp_path: Path,
) -> None:
    kept = item("Kept story")
    absent = item("Absent story", url="https://example.com/absent")
    write_legacy(tmp_path, PAST, [item("Legacy supplement")])
    publish(
        PublicationStorage(tmp_path),
        PAST,
        [kept],
        report_items=[absent, kept],
    )

    result = load(tmp_path)

    assert result.state == "partial"
    assert result.runs_loaded == 1
    assert [(story.report_position, story.item.title) for story in result.stories] == [
        (2, "Kept story")
    ]
    assert codes(result) == ["unusable_report_story"]


def test_mutable_shared_url_does_not_replace_exact_reconciliation(
    tmp_path: Path,
) -> None:
    shared = "https://example.com/product"
    raw = item("Model launch", url=shared)
    rendered = item("Compiler update", url=shared)
    publish(
        PublicationStorage(tmp_path),
        PAST,
        [raw],
        report_items=[rendered],
    )

    result = load(tmp_path)

    assert result.stories == ()
    assert codes(result) == ["unusable_report_story"]


def test_unselected_raw_item_and_raw_only_fact_do_not_enter_history(
    tmp_path: Path,
) -> None:
    selected = item("Selected story")
    raw_only = item(
        "Raw-only story",
        detail="Raw-only fact that was never rendered.",
    )
    publish(
        PublicationStorage(tmp_path),
        PAST,
        [selected, raw_only],
        report_items=[selected],
    )

    result = load(tmp_path)

    assert [story.item.title for story in result.stories] == ["Selected story"]
    assert all(
        "Raw-only fact" not in detail
        for story in result.stories
        for detail in story.item.technical_details
    )


def test_strict_source_filtering_round_trips_manifest_publication(
    tmp_path: Path,
) -> None:
    supported = Source(
        title="Primary source",
        url="https://EXAMPLE.com/filtered/#release",
        source_type="official",
        evidence_roles=["event", "event_date", "technical"],
        fact_support=FactSupport(
            summary=True,
            technical_detail_indices=[0],
            benchmark=False,
        ),
    )
    background = Source(
        title="Background source",
        url="https://example.com/filtered/background",
        source_type="official",
        evidence_roles=["background"],
        fact_support=FactSupport(
            summary=False,
            technical_detail_indices=[],
            benchmark=False,
        ),
    )
    removed = Source(
        title="Removed source",
        url="not-a-usable-url",
        source_type="official",
        evidence_roles=["background"],
        fact_support=FactSupport(
            summary=False,
            technical_detail_indices=[],
            benchmark=False,
        ),
    )
    raw_item = item("Filtered story").model_copy(
        update={"sources": [supported, background, removed]},
        deep=True,
    )
    original = ResearchRun(
        date_range=PAST,
        categories=[
            CategoryResearchResult(
                category=category,
                items=[raw_item] if category == CATEGORY else [],
            )
            for category in RESEARCH_CATEGORIES
        ],
    )
    accepted = verify_research_run(
        original,
        require_provenance=True,
    ).accepted_run.categories[0].items[0]
    storage = PublicationStorage(tmp_path)
    with storage.acquire_lock(PAST) as lock:
        attempt = storage.allocate_attempt(PAST, lock=lock, run_id="f" * 32)
        storage.write_raw(attempt, original, lock=lock)
        storage.write_report(
            attempt,
            production_report(PAST, [accepted]),
            lock=lock,
        )
        storage.publish(
            attempt,
            application_version="0.5.0",
            lock=lock,
            published_at=PUBLISHED_AT,
        )

    result = load(tmp_path)

    assert result.state == "complete"
    assert result.stories[0].item == raw_item
    assert "not-a-usable-url" not in production_report(PAST, [accepted])


def test_legacy_relative_paths_keep_existing_strict_boundary(tmp_path: Path) -> None:
    write_legacy(
        tmp_path,
        PAST,
        [item("Relative legacy")],
        relative_paths=True,
    )

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert codes(result) == ["unsafe_raw_path"]


def test_time_filter_and_unified_newest_first_cap(tmp_path: Path) -> None:
    current = DateRange(start=date(2026, 10, 25), end=date(2026, 10, 31))
    ranges = [
        DateRange(
            start=date(2026, 9, 13) + timedelta(days=7 * index),
            end=date(2026, 9, 19) + timedelta(days=7 * index),
        )
        for index in range(5)
    ]
    storage = PublicationStorage(tmp_path)
    for index, date_range in enumerate(ranges):
        story = item(f"Story {index}", date_range)
        if index % 2:
            publish(storage, date_range, [story], run_id=str(index) * 32)
        else:
            write_legacy(tmp_path, date_range, [story])
    overlap = DateRange(start=date(2026, 10, 29), end=date(2026, 10, 30))
    publish(storage, overlap, [item("Earlier-ending overlap", overlap)], run_id="a" * 32)
    publish(storage, current, [item("Current must be excluded", current)], run_id="b" * 32)
    same_end = DateRange(start=date(2026, 9, 14), end=current.end)
    publish(
        storage,
        same_end,
        [item("Same-end range must be excluded", same_end)],
        run_id="d" * 32,
    )
    future = DateRange(start=date(2026, 11, 1), end=date(2026, 11, 7))
    publish(storage, future, [item("Future must be excluded", future)], run_id="c" * 32)

    result = load(tmp_path, current)

    assert result.runs_loaded == HISTORY_LOOKBACK_RUNS
    assert [story.item.title for story in result.stories] == [
        "Earlier-ending overlap",
        "Story 4",
        "Story 3",
        "Story 2",
    ]


def test_bad_and_empty_ranges_do_not_consume_usable_cap(tmp_path: Path) -> None:
    storage = PublicationStorage(tmp_path)
    bad = PAST
    empty = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    older = DateRange(start=date(2026, 8, 23), end=date(2026, 8, 29))
    _, bad_publication = publish(storage, bad, [item("Bad")])
    bad_publication.report_path.unlink()
    publish(storage, empty, [], run_id="2" * 32)
    write_legacy(tmp_path, older, [item("Older survives", older)])

    result = load(tmp_path, lookback_runs=1)

    assert result.runs_loaded == 1
    assert [story.item.title for story in result.stories] == ["Older survives"]
    assert codes(result) == ["invalid_publication"]


def test_missing_and_empty_published_directory_are_not_damage(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "data" / "runs"
    runs.mkdir(parents=True)
    first = load(tmp_path)
    (runs / "published").mkdir()
    second = load(tmp_path)

    assert first.state == second.state == "unavailable"
    assert first.diagnostics == second.diagnostics == ()


def test_unsafe_publication_directory_blocks_legacy_fallback(tmp_path: Path) -> None:
    write_legacy(tmp_path, PAST, [item("Legacy story")])
    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / "data" / "runs" / "published").symlink_to(
        external,
        target_is_directory=True,
    )

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert result.stories == ()
    assert codes(result) == ["publication_discovery_failed"]


def test_unreadable_publication_directory_blocks_legacy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_legacy(tmp_path, PAST, [item("Legacy story")])
    published = tmp_path / "data" / "runs" / "published"
    published.mkdir()
    original = Path.iterdir

    def fail_for_published(path: Path):
        if path == published:
            raise PermissionError("fixture denies enumeration")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", fail_for_published)

    result = load(tmp_path)

    assert result.state == "unavailable"
    assert codes(result) == ["publication_discovery_failed"]


def test_manifest_filename_controls_authority_and_temporary_files_are_ignored(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, publication = publish(storage, PAST, [item("Range R")])
    other = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    write_legacy(tmp_path, PAST, [item("Masked R legacy")])
    write_legacy(tmp_path, other, [item("Range S legacy", other)])
    payload = json.loads(publication.manifest_path.read_text(encoding="utf-8"))
    payload["date_range"] = {
        "start": other.start.isoformat(),
        "end": other.end.isoformat(),
    }
    publication.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    published = publication.manifest_path.parent
    (published / ".staged-manifest.tmp").write_text("temporary", encoding="utf-8")
    (published / "unexpected.json").write_text("not authority", encoding="utf-8")

    result = load(tmp_path)

    assert [story.item.title for story in result.stories] == ["Range S legacy"]
    assert codes(result) == [
        "unexpected_publication_filename",
        "invalid_publication",
    ]
    assert result.skipped_count == 2


def test_snapshot_bytes_are_not_reopened_or_mixed_across_publications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = PublicationStorage(tmp_path)
    _, first = publish(storage, PAST, [item("Snapshot A")])
    publish(
        storage,
        PAST,
        [item("Snapshot B")],
        run_id="2" * 32,
        overwrite=True,
    )
    before = tree_bytes(tmp_path)
    real_reader = storage.read_publication
    calls = 0

    def return_frozen_snapshot(date_range: DateRange):
        nonlocal calls
        calls += 1
        return first

    monkeypatch.setattr(storage, "read_publication", return_frozen_snapshot)
    frozen = load_publication_history(CURRENT, storage=storage)
    monkeypatch.setattr(storage, "read_publication", real_reader)
    current = load_publication_history(CURRENT, storage=storage)

    assert calls == 1
    assert [story.item.title for story in frozen.stories] == ["Snapshot A"]
    assert [story.item.title for story in current.stories] == ["Snapshot B"]
    assert tree_bytes(tmp_path) == before


def test_repeated_stable_mixed_reads_are_deterministic_and_read_only(
    tmp_path: Path,
) -> None:
    storage = PublicationStorage(tmp_path)
    publish(storage, PAST, [item("Manifest story")])
    older = DateRange(start=date(2026, 8, 30), end=date(2026, 9, 5))
    write_legacy(tmp_path, older, [item("Legacy story", older)])
    before = tree_bytes(tmp_path)

    first = load_publication_history(CURRENT, storage=storage)
    second = load_publication_history(CURRENT, storage=storage)

    assert first == second
    assert tree_bytes(tmp_path) == before


def test_mixed_lookback_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lookback_runs"):
        load(tmp_path, lookback_runs=0)


@pytest.mark.parametrize("empty", [False, True])
def test_exact_legacy_preflight_confirms_valid_canonical_publication(
    tmp_path: Path,
    empty: bool,
) -> None:
    write_legacy(tmp_path, PAST, [] if empty else [item("Legacy story")])
    storage = PublicationStorage(tmp_path)

    result = check_legacy_publication(PAST, storage=storage)

    assert result.state == "published"
    assert result.diagnostic is None


def test_exact_legacy_preflight_ignores_unrelated_damage_and_same_week_range(
    tmp_path: Path,
) -> None:
    other = DateRange(start=date(2026, 9, 5), end=PAST.end)
    write_legacy(tmp_path, other, [item("Other range", other)])
    (tmp_path / "data" / "runs" / "unrelated.json").write_text(
        "{broken unrelated record",
        encoding="utf-8",
    )

    result = check_legacy_publication(
        PAST,
        storage=PublicationStorage(tmp_path),
    )

    assert result.state == "absent"


@pytest.mark.parametrize("damage", ["malformed", "duplicate", "artifact"])
def test_exact_legacy_preflight_fails_closed_for_related_ambiguity(
    tmp_path: Path,
    damage: str,
) -> None:
    canonical = write_legacy(tmp_path, PAST, [item("Legacy story")])
    if damage == "malformed":
        canonical.write_text("{broken", encoding="utf-8")
    elif damage == "duplicate":
        canonical.with_name("duplicate.json").write_bytes(canonical.read_bytes())
    else:
        (tmp_path / "reports" / weekly_report_filename(PAST)).unlink()

    result = check_legacy_publication(
        PAST,
        storage=PublicationStorage(tmp_path),
    )

    assert result.state == "invalid"
    assert result.diagnostic is not None


def test_exact_legacy_preflight_does_not_treat_failed_record_as_publication(
    tmp_path: Path,
) -> None:
    run_path = write_legacy(tmp_path, PAST, [item("Failed attempt")])
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    payload["error_stage"] = "research"
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    result = check_legacy_publication(
        PAST,
        storage=PublicationStorage(tmp_path),
    )

    assert result.state == "absent"


@pytest.mark.parametrize("symlink_target", ["runs_root", "canonical_record"])
def test_exact_legacy_preflight_rejects_required_symlink_paths(
    tmp_path: Path,
    symlink_target: str,
) -> None:
    if symlink_target == "runs_root":
        outside = tmp_path / "outside-runs"
        outside.mkdir()
        runs_root = tmp_path / "data" / "runs"
        runs_root.parent.mkdir(parents=True)
        runs_root.symlink_to(outside, target_is_directory=True)
    else:
        run_path = write_legacy(tmp_path, PAST, [item("Legacy story")])
        outside = tmp_path / "outside-run.json"
        outside.write_bytes(run_path.read_bytes())
        run_path.unlink()
        run_path.symlink_to(outside)

    result = check_legacy_publication(
        PAST,
        storage=PublicationStorage(tmp_path),
    )

    assert result.state == "invalid"
    assert result.diagnostic is not None
