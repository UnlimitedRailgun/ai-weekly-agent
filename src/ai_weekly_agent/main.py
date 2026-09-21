"""Minimal synchronous command-line pipeline for the AI Weekly Agent."""

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
import sys

from ai_weekly_agent import __version__
from ai_weekly_agent.config import AppConfig, create_openai_client, load_config
from ai_weekly_agent.curate import (
    CurationStatistics,
    CuratorError,
    curate_research_run,
)
from ai_weekly_agent.dates import (
    get_date_range_for_days,
    get_default_date_range,
    get_explicit_date_range,
)
from ai_weekly_agent.models import DateRange, ResearchRun, VerificationResult
from ai_weekly_agent.history import (
    HistoryLoadResult,
    check_legacy_publication,
    load_publication_history,
)
from ai_weekly_agent.report import (
    EmptyReportReason,
    ReportError,
    generate_report,
)
from ai_weekly_agent.research import (
    ResearchError,
    research_all_categories,
)
from ai_weekly_agent.storage import (
    AttemptPaths,
    InvalidPublicationError,
    PublicationCommitError,
    PublicationCommitInterrupted,
    PublicationLock,
    PublicationStorage,
    StorageError,
)
from ai_weekly_agent.telemetry import (
    RunErrorStage,
    RunRecord,
    RunStatus,
    HistoricalStatusCounts,
    HistoryTelemetrySummary,
    PublicationTelemetrySummary,
    TelemetryRecorder,
    observe_openai_client,
    serialize_run_record,
)
from ai_weekly_agent.verify import VerificationError, verify_research_run


class _CLIUsageError(ValueError):
    """Raised for invalid command-line argument combinations."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """Turn argparse usage errors into a returnable CLI failure."""
        raise _CLIUsageError(message)


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        )
    return parsed


def _positive_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "days must be a positive integer"
        ) from exc
    if days <= 0:
        raise argparse.ArgumentTypeError("days must be a positive integer")
    return days


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="ai-weekly",
        description=(
            "Research and write a weekly AI and Computer Engineering report."
        ),
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        help="start date (YYYY-MM-DD)",
    )
    parser.add_argument("--end", type=_parse_date, help="end date (YYYY-MM-DD)")
    parser.add_argument(
        "--days",
        type=_positive_days,
        help="inclusive number of calendar days ending today",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="publish a new immutable result for the exact date range",
    )
    return parser


def _determine_date_range(args: argparse.Namespace) -> DateRange:
    has_start = args.start is not None
    has_end = args.end is not None

    if args.days is not None and (has_start or has_end):
        raise _CLIUsageError(
            "--days cannot be combined with --start or --end"
        )
    if has_start != has_end:
        raise _CLIUsageError("--start and --end must be supplied together")

    try:
        if args.days is not None:
            return get_date_range_for_days(args.days)
        if has_start:
            return get_explicit_date_range(args.start, args.end)
        return get_default_date_range()
    except ValueError as exc:
        raise _CLIUsageError(f"invalid date range: {exc}") from exc


def _candidate_count(research_run: ResearchRun) -> int:
    return sum(len(category.items) for category in research_run.categories)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _create_storage() -> PublicationStorage:
    """Create the one storage boundary rooted at the current working directory."""
    return PublicationStorage(Path.cwd())


def _history_telemetry(
    history_result: HistoryLoadResult | None,
    statistics: CurationStatistics | None,
) -> HistoryTelemetrySummary | None:
    if history_result is None:
        return None

    status_counts = None
    if statistics is not None and statistics.validated_status_counts is not None:
        counts = statistics.validated_status_counts
        status_counts = HistoricalStatusCounts(
            new=counts["NEW"],
            follow_up=counts["FOLLOW_UP"],
            repeat=counts["REPEAT"],
            uncertain=counts["UNCERTAIN"],
        )

    return HistoryTelemetrySummary(
        load_state=history_result.state,
        usable_run_count=history_result.runs_loaded,
        reconstructed_story_count=len(history_result.stories),
        skipped_entry_count=history_result.skipped_count,
        prepared_candidate_count=(
            statistics.prepared_candidate_count
            if statistics is not None
            else None
        ),
        matched_current_candidate_count=(
            statistics.matched_current_candidate_count
            if statistics is not None
            else None
        ),
        validated_status_counts=status_counts,
        repeats_suppressed=(
            statistics.repeats_suppressed
            if statistics is not None
            else None
        ),
        selected_follow_up_count=(
            statistics.selected_follow_up_count
            if statistics is not None
            else None
        ),
    )


def _warn_about_history(history_result: HistoryLoadResult) -> None:
    if not history_result.diagnostics:
        return
    diagnostic_codes = ", ".join(
        sorted({diagnostic.code for diagnostic in history_result.diagnostics})
    )
    print(
        "Warning: Local history is "
        f"{history_result.state}; skipped {history_result.skipped_count} "
        f"history entries ({diagnostic_codes}).",
        file=sys.stderr,
    )


def _empty_report_reason(
    statistics: CurationStatistics,
) -> EmptyReportReason:
    prepared = statistics.prepared_candidate_count
    if prepared == 0:
        return "no_prepared_candidates"
    counts = statistics.validated_status_counts
    if (
        prepared is not None
        and prepared > 0
        and counts is not None
        and sum(counts.values()) == prepared
        and counts["REPEAT"] == prepared
    ):
        return "all_repeats"
    return "no_selection"


def _build_run_record(
    *,
    date_range: DateRange,
    started_at: datetime,
    status: RunStatus,
    error_stage: RunErrorStage | None,
    config: AppConfig,
    recorder: TelemetryRecorder,
    research_run: ResearchRun | None,
    verification_result: VerificationResult | None,
    curated_item_count: int | None,
    history_result: HistoryLoadResult | None,
    curation_statistics: CurationStatistics | None,
    raw_research_path: Path | None,
    report_path: Path | None,
    publication: PublicationTelemetrySummary,
    run_record_path: Path,
) -> RunRecord | None:
    finished_at = _utc_now()
    if finished_at < started_at:
        # Keep wall-clock evidence truthful: do not clamp an inverted sample or
        # let best-effort observability invalidate the primary pipeline outcome.
        print(
            "Warning: Could not save run telemetry: UTC clock moved backwards "
            f"({started_at.isoformat()} -> {finished_at.isoformat()}); "
            "RunRecord not written.",
            file=sys.stderr,
        )
        return None
    findings = (
        verification_result.findings if verification_result is not None else []
    )
    return RunRecord(
        application_version=__version__,
        date_range=date_range,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error_stage=error_stage,
        max_retries=config.openai_max_retries,
        timeout_seconds=config.openai_timeout_seconds,
        api_calls=list(recorder.records),
        api_totals=recorder.aggregate(),
        researched_category_count=(
            len(research_run.categories) if research_run is not None else None
        ),
        researched_candidate_count=(
            _candidate_count(research_run) if research_run is not None else None
        ),
        verification_accepted_count=(
            _candidate_count(verification_result.accepted_run)
            if verification_result is not None
            else None
        ),
        verification_rejected_count=(
            len(verification_result.rejected_item_ids)
            if verification_result is not None
            else None
        ),
        verification_warning_count=(
            sum(finding.severity == "warning" for finding in findings)
            if verification_result is not None
            else None
        ),
        verification_information_count=(
            sum(finding.severity == "info" for finding in findings)
            if verification_result is not None
            else None
        ),
        curated_item_count=curated_item_count,
        history=_history_telemetry(history_result, curation_statistics),
        publication=publication,
        raw_research_path=raw_research_path,
        report_path=report_path,
        run_record_path=run_record_path,
    )


def _save_run_record_best_effort(
    run_record: RunRecord | None,
    *,
    storage: PublicationStorage,
    attempt: AttemptPaths,
    lock: PublicationLock,
) -> Path | None:
    if run_record is None:
        return None
    try:
        content = serialize_run_record(run_record)
        return storage.write_attempt_run_record(
            attempt,
            content,
            lock=lock,
        )
    except (OSError, ValueError, StorageError) as exc:
        print(f"Warning: Could not save run telemetry: {exc}", file=sys.stderr)
        return None


def _publication_summary(
    run_id: str,
    state: str,
    durability: str,
) -> PublicationTelemetrySummary:
    confirmed: bool | None = None
    if state == "published":
        confirmed = durability == "confirmed"
    return PublicationTelemetrySummary(
        run_id=run_id,
        state=state,
        durability_confirmed=confirmed,
    )


def _preflight_publication(
    date_range: DateRange,
    *,
    storage: PublicationStorage,
    overwrite: bool,
) -> bool:
    try:
        publication = storage.read_publication(date_range)
    except InvalidPublicationError as exc:
        print(
            "Error: Existing exact-range publication is invalid or unreadable: "
            f"{exc}",
            file=sys.stderr,
        )
        return False

    if publication is not None:
        if not overwrite:
            print(
                "Error: A publication already exists for this exact date "
                f"range: {publication.manifest_path}",
                file=sys.stderr,
            )
            return False
        return True

    legacy = check_legacy_publication(date_range, storage=storage)
    if legacy.state == "invalid":
        diagnostic = legacy.diagnostic
        detail = diagnostic.message if diagnostic is not None else "unknown"
        print(
            "Error: Exact-range legacy publication cannot be safely confirmed: "
            f"{detail}",
            file=sys.stderr,
        )
        return False
    if legacy.state == "published" and not overwrite:
        print(
            "Error: A legacy publication already exists for this exact date "
            "range; use --overwrite to publish a new immutable revision.",
            file=sys.stderr,
        )
        return False
    return True


def _attempt_record(
    *,
    date_range: DateRange,
    started_at: datetime,
    status: RunStatus,
    error_stage: RunErrorStage | None,
    config: AppConfig,
    recorder: TelemetryRecorder,
    research_run: ResearchRun | None,
    verification_result: VerificationResult | None,
    curated_item_count: int | None,
    history_result: HistoryLoadResult | None,
    curation_statistics: CurationStatistics | None,
    raw_path: Path | None,
    report_path: Path | None,
    publication: PublicationTelemetrySummary,
    storage: PublicationStorage,
    attempt: AttemptPaths,
    lock: PublicationLock,
) -> Path | None:
    try:
        run_record_path = storage.attempt_run_record_path(attempt, lock=lock)
        record = _build_run_record(
            date_range=date_range,
            started_at=started_at,
            status=status,
            error_stage=error_stage,
            config=config,
            recorder=recorder,
            research_run=research_run,
            verification_result=verification_result,
            curated_item_count=curated_item_count,
            history_result=history_result,
            curation_statistics=curation_statistics,
            raw_research_path=raw_path,
            report_path=report_path,
            publication=publication,
            run_record_path=run_record_path,
        )
        return _save_run_record_best_effort(
            record,
            storage=storage,
            attempt=attempt,
            lock=lock,
        )
    except (OSError, ValueError, StorageError) as exc:
        print(f"Warning: Could not save run telemetry: {exc}", file=sys.stderr)
        return None


def _print_commit_failure(
    state: str,
    durability: str,
    error: BaseException,
) -> None:
    if state == "published":
        print(
            "Error: The report is published, but publication durability is "
            f"unconfirmed: {error}",
            file=sys.stderr,
        )
    elif state == "unknown":
        print(
            f"Error: Publication outcome is unknown: {error}",
            file=sys.stderr,
        )
    else:
        print(f"Error: The attempt was not published: {error}", file=sys.stderr)


def _run_locked(
    date_range: DateRange,
    *,
    overwrite: bool,
    storage: PublicationStorage,
    lock: PublicationLock,
) -> int:
    if not _preflight_publication(
        date_range,
        storage=storage,
        overwrite=overwrite,
    ):
        return 1

    try:
        config = load_config()
        config.require_openai_configuration()
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        attempt = storage.allocate_attempt(date_range, lock=lock)
    except StorageError as exc:
        print(f"Error: Could not allocate run attempt: {exc}", file=sys.stderr)
        return 1

    run_started_at = _utc_now()
    recorder = TelemetryRecorder()
    research_run: ResearchRun | None = None
    verification_result: VerificationResult | None = None
    curated_item_count: int | None = None
    history_result: HistoryLoadResult | None = None
    curation_statistics: CurationStatistics | None = None
    raw_path: Path | None = None
    report_path: Path | None = None
    current_stage: RunErrorStage = "research"
    not_published = _publication_summary(
        attempt.run_id,
        "not_published",
        "not_applicable",
    )

    def save_attempt_record(
        *,
        status: RunStatus,
        error_stage: RunErrorStage | None,
        publication: PublicationTelemetrySummary,
    ) -> Path | None:
        return _attempt_record(
            date_range=date_range,
            started_at=run_started_at,
            status=status,
            error_stage=error_stage,
            config=config,
            recorder=recorder,
            research_run=research_run,
            verification_result=verification_result,
            curated_item_count=curated_item_count,
            history_result=history_result,
            curation_statistics=curation_statistics,
            raw_path=raw_path,
            report_path=report_path,
            publication=publication,
            storage=storage,
            attempt=attempt,
            lock=lock,
        )

    try:
        base_client = create_openai_client(config)

        def client_for_research_category(category: str) -> object:
            return observe_openai_client(
                base_client,
                recorder,
                "research",
                research_category=category,
            )

        print("[1/5] Researching AI and Computer Engineering developments...")
        research_run = research_all_categories(
            date_range,
            config,
            client_for_category=client_for_research_category,
        )
        print(f"Research candidates: {_candidate_count(research_run)}")

        current_stage = "save"
        print("[2/5] Saving original research...")
        raw_path = storage.write_raw(attempt, research_run, lock=lock).path
        print("Raw research saved:")
        print(raw_path)

        current_stage = "verify"
        print("[3/5] Verifying research evidence...")
        verification_result = verify_research_run(
            research_run,
            require_provenance=True,
        )
        accepted_count = _candidate_count(verification_result.accepted_run)
        rejected_count = len(verification_result.rejected_item_ids)
        warning_count = sum(
            finding.severity == "warning"
            for finding in verification_result.findings
        )
        print(
            f"Verified {_candidate_count(research_run)} items: "
            f"{accepted_count} accepted, {rejected_count} rejected, "
            f"{warning_count} warnings."
        )

        current_stage = "curate"
        print("Loading local report history...")
        history_result = load_publication_history(
            date_range,
            storage=storage,
        )
        _warn_about_history(history_result)

        print("[4/5] Curating candidate stories...")
        curate_client = observe_openai_client(base_client, recorder, "curate")
        curation_statistics = CurationStatistics()
        curated_items = curate_research_run(
            verification_result.accepted_run,
            config,
            client=curate_client,
            history=history_result,
            statistics=curation_statistics,
        )
        curated_item_count = len(curated_items)
        print(f"Curated stories: {len(curated_items)}")

        current_stage = "report"
        print("[5/5] Generating weekly report...")
        if curated_items:
            report_client = observe_openai_client(base_client, recorder, "report")
            markdown = generate_report(
                date_range,
                curated_items,
                config,
                client=report_client,
            )
        else:
            markdown = generate_report(
                date_range,
                curated_items,
                config,
                empty_reason=_empty_report_reason(curation_statistics),
            )

        current_stage = "save"
        report_path = storage.write_report(
            attempt,
            markdown,
            lock=lock,
        ).path
        print("Attempt report saved:")
        print(report_path)
        commit = storage.publish(
            attempt,
            application_version=__version__,
            lock=lock,
            overwrite=overwrite,
        )
    except PublicationCommitError as exc:
        publication = _publication_summary(
            attempt.run_id,
            exc.state,
            exc.durability,
        )
        save_attempt_record(
            status="failed",
            error_stage="save",
            publication=publication,
        )
        _print_commit_failure(exc.state, exc.durability, exc)
        return 1
    except PublicationCommitInterrupted as exc:
        publication = _publication_summary(
            attempt.run_id,
            exc.state,
            exc.durability,
        )
        save_attempt_record(
            status="failed",
            error_stage="save",
            publication=publication,
        )
        _print_commit_failure(exc.state, exc.durability, exc)
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except (
        ResearchError,
        VerificationError,
        CuratorError,
        ReportError,
        OSError,
        StorageError,
    ) as exc:
        save_attempt_record(
            status="failed",
            error_stage=current_stage,
            publication=not_published,
        )
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        save_attempt_record(
            status="failed",
            error_stage=current_stage,
            publication=not_published,
        )
        print(
            "Interrupted by user. This attempt was not published.",
            file=sys.stderr,
        )
        return 130

    publication = _publication_summary(
        attempt.run_id,
        commit.state,
        commit.durability,
    )
    try:
        run_record_path = save_attempt_record(
            status="success",
            error_stage=None,
            publication=publication,
        )
    except KeyboardInterrupt:
        print(
            "Interrupted after publication; telemetry may be incomplete.",
            file=sys.stderr,
        )
        return 130
    if run_record_path is not None:
        print("Run telemetry saved:")
        print(run_record_path)

    print("Weekly report published:")
    print(commit.publication.report_path)
    totals = recorder.aggregate()
    print(f"API calls: {totals.logical_call_count}")
    if totals.usage_complete:
        print(f"Tokens: {totals.total_tokens}")
    else:
        print("Tokens: incomplete telemetry")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the synchronous weekly pipeline and return a process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        date_range = _determine_date_range(args)
    except _CLIUsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(f"Try '{parser.prog} --help' for usage.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    print(f"AI Weekly Agent v{__version__}")
    print()
    print(
        "Reporting period: "
        f"{date_range.start.isoformat()} -> {date_range.end.isoformat()}"
    )
    print()

    try:
        storage = _create_storage()
        lock = storage.acquire_lock(date_range)
        with lock:
            return _run_locked(
                date_range,
                overwrite=args.overwrite,
                storage=storage,
                lock=lock,
            )
    except StorageError as exc:
        print(f"Error: Storage operation failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
