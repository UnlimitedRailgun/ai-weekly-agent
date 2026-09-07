"""Minimal synchronous command-line pipeline for the AI Weekly Agent."""

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import sys

from ai_weekly_agent.config import load_config
from ai_weekly_agent.curate import CuratorError, curate_research_run
from ai_weekly_agent.dates import (
    get_date_range_for_days,
    get_default_date_range,
    get_explicit_date_range,
    weekly_report_filename,
)
from ai_weekly_agent.models import DateRange, ResearchRun
from ai_weekly_agent.report import ReportError, generate_report, save_report
from ai_weekly_agent.research import (
    ResearchError,
    research_all_categories,
    save_research_run,
)


RAW_DATA_DIR = Path("data/raw")
REPORTS_DIR = Path("reports")


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
        help="replace an existing final report",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Version 0.1 pipeline and return a process exit code."""
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

    print("AI Weekly Agent v0.1")
    print()
    print(
        "Reporting period: "
        f"{date_range.start.isoformat()} -> {date_range.end.isoformat()}"
    )
    print()

    intended_report = REPORTS_DIR / weekly_report_filename(date_range)
    if intended_report.exists() and not args.overwrite:
        print(f"Error: Report already exists: {intended_report}", file=sys.stderr)
        return 1

    try:
        config = load_config()
        config.require_openai_configuration()
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    try:
        print("[1/4] Researching AI and Computer Engineering developments...")
        research_run = research_all_categories(date_range, config)
        print(f"Research candidates: {_candidate_count(research_run)}")

        print("[2/4] Saving validated research...")
        raw_path = save_research_run(research_run, output_dir=RAW_DATA_DIR)
        print("Raw research saved:")
        print(raw_path)

        print("[3/4] Curating candidate stories...")
        curated_items = curate_research_run(research_run, config)
        print(f"Curated stories: {len(curated_items)}")

        print("[4/4] Generating weekly report...")
        markdown = generate_report(date_range, curated_items, config)
        report_path = save_report(
            date_range,
            markdown,
            output_dir=REPORTS_DIR,
            overwrite=args.overwrite,
        )
        print("Weekly report saved:")
        print(report_path)
    except (ResearchError, CuratorError, ReportError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
