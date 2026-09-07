from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import ai_weekly_agent.main as main_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.curate import CuratorError
from ai_weekly_agent.models import (
    CategoryResearchResult,
    CuratedItem,
    DateRange,
    NewsItem,
    ResearchRun,
    Source,
)
from ai_weekly_agent.report import ReportError
from ai_weekly_agent.research import ResearchError


DATE_RANGE = DateRange(start=date(2026, 9, 1), end=date(2026, 9, 7))
CONFIG = AppConfig(openai_api_key="test-key", openai_model="test-model")


def make_item(number: int) -> NewsItem:
    return NewsItem(
        title=f"Story {number}",
        category="AI model releases",
        organization="Example Lab",
        published_date=date(2026, 9, number),
        summary=f"Summary {number}",
        technical_details=[f"Detail {number}"],
        benchmark_information=None,
        sources=[
            Source(
                title=f"Source {number}",
                url=f"https://example.com/story-{number}",
                source_type="official",
            )
        ],
    )


def make_research_run(*items: NewsItem) -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            CategoryResearchResult(
                category="AI model releases",
                items=list(items),
            ),
            CategoryResearchResult(category="AI research", items=[]),
        ],
    )


def install_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    research_run: ResearchRun | None = None,
    curated_items: list[CuratedItem] | None = None,
) -> SimpleNamespace:
    items = [make_item(1), make_item(2)]
    run = research_run if research_run is not None else make_research_run(*items)
    curated = (
        curated_items
        if curated_items is not None
        else [CuratedItem(item=item, final_score=4.0) for item in items]
    )
    raw_path = tmp_path / "raw" / "research.json"
    report_path = tmp_path / "reports" / "2026-W37.md"
    mocks = SimpleNamespace(
        load_config=Mock(return_value=CONFIG),
        research=Mock(return_value=run),
        save_research=Mock(return_value=raw_path),
        curate=Mock(return_value=curated),
        generate=Mock(return_value="# Weekly report\n"),
        save_report=Mock(return_value=report_path),
        run=run,
        curated=curated,
        raw_path=raw_path,
        report_path=report_path,
    )

    monkeypatch.setattr(main_module, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(main_module, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(main_module, "load_config", mocks.load_config)
    monkeypatch.setattr(
        main_module,
        "research_all_categories",
        mocks.research,
    )
    monkeypatch.setattr(
        main_module,
        "save_research_run",
        mocks.save_research,
    )
    monkeypatch.setattr(main_module, "curate_research_run", mocks.curate)
    monkeypatch.setattr(main_module, "generate_report", mocks.generate)
    monkeypatch.setattr(main_module, "save_report", mocks.save_report)
    return mocks


def test_default_uses_seven_inclusive_calendar_dates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    get_default = Mock(return_value=DATE_RANGE)
    monkeypatch.setattr(main_module, "get_default_date_range", get_default)

    result = main_module.main([])

    assert result == 0
    get_default.assert_called_once_with()
    mocks.research.assert_called_once_with(DATE_RANGE, CONFIG)


@pytest.mark.parametrize(
    ("days", "expected_start"),
    [(7, date(2026, 9, 1)), (3, date(2026, 9, 5))],
)
def test_days_uses_inclusive_relative_date_utility(
    days: int,
    expected_start: date,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = DateRange(start=expected_start, end=date(2026, 9, 7))
    mocks = install_pipeline(monkeypatch, tmp_path)
    get_relative = Mock(return_value=expected)
    monkeypatch.setattr(main_module, "get_date_range_for_days", get_relative)

    result = main_module.main(["--days", str(days)])

    assert result == 0
    get_relative.assert_called_once_with(days)
    mocks.research.assert_called_once_with(expected, CONFIG)


@pytest.mark.parametrize("days", ["0", "-1"])
def test_non_positive_days_are_rejected(
    days: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    result = main_module.main(["--days", days])

    assert result == 2
    assert "days must be a positive integer" in capsys.readouterr().err
    mocks.research.assert_not_called()


def test_explicit_start_and_end_are_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    result = main_module.main(
        ["--start", "2026-09-01", "--end", "2026-09-07"]
    )

    assert result == 0
    mocks.research.assert_called_once_with(DATE_RANGE, CONFIG)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--start", "2026-09-01"],
        ["--end", "2026-09-07"],
        ["--days", "7", "--start", "2026-09-01", "--end", "2026-09-07"],
    ],
)
def test_invalid_date_argument_combinations_fail_cleanly(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    result = main_module.main(arguments)

    assert result == 2
    assert "Error:" in capsys.readouterr().err
    mocks.research.assert_not_called()


@pytest.mark.parametrize("invalid_date", ["September-1", "20260901"])
def test_invalid_date_string_fails_clearly(
    invalid_date: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    result = main_module.main(
        ["--start", invalid_date, "--end", "2026-09-07"]
    )

    assert result == 2
    assert "expected YYYY-MM-DD" in capsys.readouterr().err
    mocks.research.assert_not_called()


def test_pipeline_order_data_flow_counts_and_console_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    events = Mock()
    mocks.research.side_effect = lambda *_: (events("research"), mocks.run)[1]
    mocks.save_research.side_effect = (
        lambda *_args, **_kwargs: (events("save raw"), mocks.raw_path)[1]
    )
    mocks.curate.side_effect = lambda *_: (events("curate"), mocks.curated)[1]
    mocks.generate.side_effect = (
        lambda *_: (events("generate report"), "# Weekly report\n")[1]
    )
    mocks.save_report.side_effect = (
        lambda *_args, **_kwargs: (events("save report"), mocks.report_path)[1]
    )
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )

    result = main_module.main([])

    assert result == 0
    assert events.call_args_list == [
        call("research"),
        call("save raw"),
        call("curate"),
        call("generate report"),
        call("save report"),
    ]
    mocks.save_research.assert_called_once_with(
        mocks.run,
        output_dir=tmp_path / "raw",
    )
    mocks.curate.assert_called_once_with(mocks.run, CONFIG)
    mocks.generate.assert_called_once_with(DATE_RANGE, mocks.curated, CONFIG)
    assert mocks.generate.call_args.args[1] is mocks.curated
    mocks.save_report.assert_called_once_with(
        DATE_RANGE,
        "# Weekly report\n",
        output_dir=tmp_path / "reports",
        overwrite=False,
    )

    output = capsys.readouterr().out
    assert "Reporting period: 2026-09-01 -> 2026-09-07" in output
    assert "Research candidates: 2" in output
    assert "Curated stories: 2" in output
    assert str(mocks.raw_path) in output
    assert str(mocks.report_path) in output


def test_missing_api_configuration_fails_without_starting_research(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    mocks.load_config.return_value = AppConfig()
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )

    result = main_module.main([])

    assert result == 1
    error = capsys.readouterr().err
    assert "Missing required OpenAI configuration" in error
    assert "test-key" not in error
    mocks.research.assert_not_called()


@pytest.mark.parametrize(
    ("stage_name", "error", "expected_calls"),
    [
        ("research", ResearchError("research failed"), (0, 0, 0, 0)),
        ("save_research", ResearchError("raw save failed"), (1, 0, 0, 0)),
        ("curate", CuratorError("curation failed"), (1, 1, 0, 0)),
        ("generate", ReportError("report failed"), (1, 1, 1, 0)),
        ("save_report", ReportError("report save failed"), (1, 1, 1, 1)),
    ],
)
def test_expected_stage_failure_is_not_retried_and_stops_pipeline(
    stage_name: str,
    error: Exception,
    expected_calls: tuple[int, int, int, int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    getattr(mocks, stage_name).side_effect = error

    result = main_module.main([])

    assert result == 1
    assert str(error) in capsys.readouterr().err
    assert mocks.research.call_count == 1
    assert (
        mocks.save_research.call_count,
        mocks.curate.call_count,
        mocks.generate.call_count,
        mocks.save_report.call_count,
    ) == expected_calls


def test_raw_oserror_returns_nonzero_without_curation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.save_research.side_effect = OSError("disk unavailable")

    result = main_module.main([])

    assert result == 1
    mocks.save_research.assert_called_once()
    mocks.curate.assert_not_called()


def test_report_persistence_oserror_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.save_report.side_effect = OSError("disk unavailable")

    result = main_module.main([])

    assert result == 1
    mocks.save_report.assert_called_once()


def test_keyboard_interrupt_returns_nonzero_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.research.side_effect = KeyboardInterrupt

    result = main_module.main([])

    assert result == 130
    assert "Interrupted by user." in capsys.readouterr().err
    mocks.research.assert_called_once()
    mocks.save_research.assert_not_called()


@pytest.mark.parametrize("curated_count", [0, 3])
def test_zero_or_fewer_than_eight_curated_stories_are_allowed(
    curated_count: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = make_research_run() if curated_count == 0 else make_research_run(
        make_item(1),
        make_item(2),
        make_item(3),
    )
    curated = [
        CuratedItem(item=item, final_score=4.0)
        for item in run.categories[0].items[:curated_count]
    ]
    mocks = install_pipeline(
        monkeypatch,
        tmp_path,
        research_run=run,
        curated_items=curated,
    )
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )

    result = main_module.main([])

    assert result == 0
    mocks.generate.assert_called_once_with(DATE_RANGE, curated, CONFIG)
    mocks.save_report.assert_called_once()


def test_overwrite_flag_is_forwarded_to_report_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )

    result = main_module.main(["--overwrite"])

    assert result == 0
    assert mocks.save_report.call_args.kwargs["overwrite"] is True


def test_existing_report_stops_before_configuration_and_research(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    report_path = tmp_path / "reports" / "2026-W37.md"
    report_path.parent.mkdir()
    report_path.write_text("existing report\n", encoding="utf-8")

    result = main_module.main([])

    assert result == 1
    assert "Report already exists" in capsys.readouterr().err
    mocks.load_config.assert_not_called()
    mocks.research.assert_not_called()


def test_overwrite_bypasses_early_report_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    report_path = tmp_path / "reports" / "2026-W37.md"
    report_path.parent.mkdir()
    report_path.write_text("existing report\n", encoding="utf-8")

    result = main_module.main(["--overwrite"])

    assert result == 0
    mocks.research.assert_called_once()
    assert mocks.save_report.call_args.kwargs["overwrite"] is True


def test_start_after_end_is_rejected_as_cli_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    result = main_module.main(
        ["--start", "2026-09-07", "--end", "2026-09-01"]
    )

    assert result == 2
    assert "start must not be after end" in capsys.readouterr().err
    mocks.research.assert_not_called()


def test_unexpected_programming_errors_are_not_silently_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.research.side_effect = RuntimeError("unexpected bug")

    with pytest.raises(RuntimeError, match="unexpected bug"):
        main_module.main([])

    mocks.research.assert_called_once()
