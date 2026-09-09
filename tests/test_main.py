import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

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
from ai_weekly_agent.research import (
    RESEARCH_CATEGORIES,
    ResearchError,
    save_research_run as persist_research_run,
)
from ai_weekly_agent.telemetry import RunRecord
from ai_weekly_agent.verify import VerificationError


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
                evidence_roles=["event", "event_date", "technical"],
            )
        ],
    )


def make_research_run(*items: NewsItem) -> ResearchRun:
    return ResearchRun(
        date_range=DATE_RANGE,
        categories=[
            CategoryResearchResult(
                category=category,
                items=list(items) if index == 0 else [],
            )
            for index, category in enumerate(RESEARCH_CATEGORIES)
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
    run_record_path = tmp_path / "runs" / "research.json"
    base_client = SimpleNamespace(
        responses=SimpleNamespace(parse=Mock()),
        marker=object(),
    )
    mocks = SimpleNamespace(
        load_config=Mock(return_value=CONFIG),
        create_client=Mock(return_value=base_client),
        research=Mock(return_value=run),
        save_research=Mock(return_value=raw_path),
        curate=Mock(return_value=curated),
        generate=Mock(return_value="# Weekly report\n"),
        save_report=Mock(return_value=report_path),
        save_run_record=Mock(return_value=run_record_path),
        base_client=base_client,
        run=run,
        curated=curated,
        raw_path=raw_path,
        report_path=report_path,
        run_record_path=run_record_path,
    )

    monkeypatch.setattr(main_module, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(main_module, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main_module, "load_config", mocks.load_config)
    monkeypatch.setattr(
        main_module,
        "create_openai_client",
        mocks.create_client,
    )
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
    monkeypatch.setattr(
        main_module,
        "save_run_record",
        mocks.save_run_record,
    )
    return mocks


def api_response(
    input_tokens: int = 10,
    output_tokens: int = 5,
    total_tokens: int = 15,
    *,
    include_usage: bool = True,
) -> SimpleNamespace:
    usage = (
        SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        if include_usage
        else None
    )
    return SimpleNamespace(model="response-model", usage=usage)


def make_stages_call_api(
    mocks: SimpleNamespace,
    *responses: object,
) -> None:
    mocks.base_client.responses.parse.side_effect = list(responses)

    def research(*_args: object, client: object) -> ResearchRun:
        client.responses.parse(model=CONFIG.openai_model)
        return mocks.run

    def curate(*_args: object, client: object) -> list[CuratedItem]:
        client.responses.parse(model=CONFIG.openai_model)
        return mocks.curated

    def report(*_args: object, client: object) -> str:
        client.responses.parse(model=CONFIG.openai_model)
        return "# Weekly report\n"

    mocks.research.side_effect = research
    mocks.curate.side_effect = curate
    mocks.generate.side_effect = report


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
    mocks.research.assert_called_once_with(DATE_RANGE, CONFIG, client=ANY)


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
    mocks.research.assert_called_once_with(expected, CONFIG, client=ANY)


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
    mocks.research.assert_called_once_with(DATE_RANGE, CONFIG, client=ANY)


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
    mocks.research.side_effect = (
        lambda *_args, **_kwargs: (events("research"), mocks.run)[1]
    )
    mocks.save_research.side_effect = (
        lambda *_args, **_kwargs: (events("save raw"), mocks.raw_path)[1]
    )
    real_verify = main_module.verify_research_run
    monkeypatch.setattr(
        main_module,
        "verify_research_run",
        lambda research_run: (
            events("verify"),
            real_verify(research_run),
        )[1],
    )
    mocks.curate.side_effect = (
        lambda *_args, **_kwargs: (events("curate"), mocks.curated)[1]
    )
    mocks.generate.side_effect = (
        lambda *_args, **_kwargs: (
            events("generate report"),
            "# Weekly report\n",
        )[1]
    )
    mocks.save_report.side_effect = (
        lambda *_args, **_kwargs: (events("save report"), mocks.report_path)[1]
    )
    mocks.save_run_record.side_effect = (
        lambda *_args, **_kwargs: (
            events("save run record"),
            mocks.run_record_path,
        )[1]
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
        call("verify"),
        call("curate"),
        call("generate report"),
        call("save report"),
        call("save run record"),
    ]
    mocks.save_research.assert_called_once_with(
        mocks.run,
        output_dir=tmp_path / "raw",
    )
    curated_run = mocks.curate.call_args.args[0]
    assert curated_run == mocks.run
    assert curated_run is not mocks.run
    mocks.curate.assert_called_once_with(curated_run, CONFIG, client=ANY)
    mocks.generate.assert_called_once_with(
        DATE_RANGE,
        mocks.curated,
        CONFIG,
        client=ANY,
    )
    assert mocks.generate.call_args.args[1] is mocks.curated
    mocks.save_report.assert_called_once_with(
        DATE_RANGE,
        "# Weekly report\n",
        output_dir=tmp_path / "reports",
        overwrite=False,
    )

    output = capsys.readouterr().out
    assert f"AI Weekly Agent v{main_module.__version__}" in output
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
    mocks.generate.assert_called_once_with(
        DATE_RANGE,
        curated,
        CONFIG,
        client=ANY,
    )
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


def test_main_creates_one_base_client_and_three_shared_observed_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    real_observe = main_module.observe_openai_client
    observations: list[tuple[object, object, str, object]] = []

    def observe(
        base_client: object,
        recorder: object,
        stage: str,
    ) -> object:
        view = real_observe(base_client, recorder, stage)
        observations.append((base_client, recorder, stage, view))
        return view

    monkeypatch.setattr(main_module, "observe_openai_client", observe)

    result = main_module.main([])

    assert result == 0
    mocks.create_client.assert_called_once_with(CONFIG)
    assert [entry[2] for entry in observations] == [
        "research",
        "curate",
        "report",
    ]
    assert all(entry[0] is mocks.base_client for entry in observations)
    assert len({id(entry[1]) for entry in observations}) == 1
    assert mocks.research.call_args.kwargs["client"] is observations[0][3]
    assert mocks.curate.call_args.kwargs["client"] is observations[1][3]
    assert mocks.generate.call_args.kwargs["client"] is observations[2][3]


def test_original_raw_run_is_saved_before_verify_and_curator_gets_accepted_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_accepted = make_item(1)
    accepted = base_accepted.model_copy(
        update={
            "published_date": None,
            "sources": [
                base_accepted.sources[0],
                base_accepted.sources[0].model_copy(deep=True),
            ],
        },
        deep=True,
    )
    rejected = make_item(2).model_copy(
        update={"published_date": date(2026, 8, 31)},
        deep=True,
    )
    original_run = make_research_run(accepted, rejected)
    original_snapshot = original_run.model_copy(deep=True)
    curated = [CuratedItem(item=accepted, final_score=4.0)]
    mocks = install_pipeline(
        monkeypatch,
        tmp_path,
        research_run=original_run,
        curated_items=curated,
    )
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    events: list[str] = []
    real_verify = main_module.verify_research_run

    def save_raw(run: ResearchRun, *, output_dir: Path) -> Path:
        events.append("save raw")
        return persist_research_run(run, output_dir=output_dir)

    def verify(run: ResearchRun) -> object:
        events.append("verify")
        return real_verify(run)

    def curate(
        run: ResearchRun,
        *_args: object,
        **_kwargs: object,
    ) -> list[CuratedItem]:
        events.append("curate")
        return curated

    mocks.save_research.side_effect = save_raw
    monkeypatch.setattr(main_module, "verify_research_run", verify)
    mocks.curate.side_effect = curate

    result = main_module.main([])

    assert result == 0
    assert events == ["save raw", "verify", "curate"]
    saved_path = tmp_path / "raw" / "2026-09-01_to_2026-09-07.json"
    raw_data = json.loads(saved_path.read_text(encoding="utf-8"))
    saved_titles = [
        item["title"]
        for category in raw_data["categories"]
        for item in category["items"]
    ]
    assert saved_titles == ["Story 1", "Story 2"]
    curated_run = mocks.curate.call_args.args[0]
    assert _titles(curated_run) == ["Story 1"]
    assert original_run == original_snapshot
    assert _titles(original_run) == ["Story 1", "Story 2"]
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.verification_accepted_count == 1
    assert run_record.verification_rejected_count == 1
    assert run_record.verification_warning_count == 1
    assert run_record.verification_information_count == 1


def test_success_run_record_contains_current_pipeline_state_and_totals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_model="test-model",
        openai_max_retries=0,
        openai_timeout_seconds=12.5,
    )
    mocks = install_pipeline(monkeypatch, tmp_path)
    mocks.load_config.return_value = config
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    make_stages_call_api(
        mocks,
        api_response(10, 2, 12),
        api_response(20, 3, 23),
        api_response(30, 4, 34),
    )

    result = main_module.main([])

    assert result == 0
    run_record = mocks.save_run_record.call_args.args[0]
    assert isinstance(run_record, RunRecord)
    assert run_record.application_version == main_module.__version__
    assert run_record.status == "success"
    assert run_record.error_stage is None
    assert run_record.date_range == DATE_RANGE
    assert run_record.max_retries == 0
    assert run_record.timeout_seconds == 12.5
    assert [record.stage for record in run_record.api_calls] == [
        "research",
        "curate",
        "report",
    ]
    assert run_record.api_totals.logical_call_count == 3
    assert run_record.api_totals.total_tokens == 69
    assert run_record.api_totals.usage_complete is True
    assert run_record.researched_category_count == 6
    assert run_record.researched_candidate_count == 2
    assert run_record.verification_accepted_count == 2
    assert run_record.verification_rejected_count == 0
    assert run_record.verification_warning_count == 0
    assert run_record.verification_information_count == 0
    assert run_record.curated_item_count == 2
    assert run_record.raw_research_path == mocks.raw_path
    assert run_record.report_path == mocks.report_path
    assert run_record.run_record_path == (
        tmp_path / "runs" / "2026-09-01_to_2026-09-07.json"
    )
    output = capsys.readouterr().out
    assert "Verified 2 items: 2 accepted, 0 rejected, 0 warnings." in output
    assert "API calls: 3" in output
    assert "Tokens: 69" in output


def test_research_failure_saves_current_failed_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    provider_error = RuntimeError("provider failed")
    mocks.base_client.responses.parse.side_effect = provider_error

    def fail_research(*_args: object, client: object) -> ResearchRun:
        try:
            client.responses.parse(model=CONFIG.openai_model)
        except RuntimeError as exc:
            raise ResearchError("research failed") from exc
        raise AssertionError("unreachable")

    mocks.research.side_effect = fail_research

    result = main_module.main([])

    assert result == 1
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.status == "failed"
    assert run_record.error_stage == "research"
    assert [record.stage for record in run_record.api_calls] == ["research"]
    assert run_record.api_calls[0].status == "failed"
    assert run_record.researched_candidate_count is None
    mocks.save_research.assert_not_called()
    mocks.curate.assert_not_called()
    mocks.generate.assert_not_called()


def test_verify_failure_retains_raw_path_and_stops_downstream_stages(
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
    verify_error = VerificationError("verification failed")
    monkeypatch.setattr(
        main_module,
        "verify_research_run",
        Mock(side_effect=verify_error),
    )

    result = main_module.main([])

    assert result == 1
    assert "verification failed" in capsys.readouterr().err
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.error_stage == "verify"
    assert run_record.raw_research_path == mocks.raw_path
    assert run_record.researched_candidate_count == 2
    assert run_record.verification_accepted_count is None
    mocks.save_research.assert_called_once()
    mocks.curate.assert_not_called()
    mocks.generate.assert_not_called()


def test_curator_failure_retains_verification_and_current_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.base_client.responses.parse.side_effect = [
        api_response(),
        RuntimeError("provider failed"),
    ]

    def research(*_args: object, client: object) -> ResearchRun:
        client.responses.parse(model=CONFIG.openai_model)
        return mocks.run

    def fail_curate(*_args: object, client: object) -> list[CuratedItem]:
        try:
            client.responses.parse(model=CONFIG.openai_model)
        except RuntimeError as exc:
            raise CuratorError("curation failed") from exc
        raise AssertionError("unreachable")

    mocks.research.side_effect = research
    mocks.curate.side_effect = fail_curate

    result = main_module.main([])

    assert result == 1
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.error_stage == "curate"
    assert [record.status for record in run_record.api_calls] == [
        "success",
        "failed",
    ]
    assert run_record.verification_accepted_count == 2
    assert run_record.verification_rejected_count == 0
    assert run_record.curated_item_count is None
    mocks.generate.assert_not_called()


def test_report_failure_retains_prior_summaries_and_failed_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    mocks.base_client.responses.parse.side_effect = [
        api_response(),
        api_response(),
        RuntimeError("provider failed"),
    ]

    def research(*_args: object, client: object) -> ResearchRun:
        client.responses.parse(model=CONFIG.openai_model)
        return mocks.run

    def curate(*_args: object, client: object) -> list[CuratedItem]:
        client.responses.parse(model=CONFIG.openai_model)
        return mocks.curated

    def fail_report(*_args: object, client: object) -> str:
        try:
            client.responses.parse(model=CONFIG.openai_model)
        except RuntimeError as exc:
            raise ReportError("report failed") from exc
        raise AssertionError("unreachable")

    mocks.research.side_effect = research
    mocks.curate.side_effect = curate
    mocks.generate.side_effect = fail_report

    result = main_module.main([])

    assert result == 1
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.error_stage == "report"
    assert [record.stage for record in run_record.api_calls] == [
        "research",
        "curate",
        "report",
    ]
    assert run_record.api_calls[-1].status == "failed"
    assert run_record.curated_item_count == 2
    assert run_record.report_path is None
    mocks.save_report.assert_not_called()


def test_raw_save_failure_records_save_stage_without_false_path(
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
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.error_stage == "save"
    assert run_record.researched_candidate_count == 2
    assert run_record.raw_research_path is None
    assert run_record.verification_accepted_count is None
    mocks.curate.assert_not_called()


def test_report_save_failure_records_save_stage_without_false_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_module,
        "get_default_date_range",
        Mock(return_value=DATE_RANGE),
    )
    make_stages_call_api(
        mocks,
        api_response(),
        api_response(),
        api_response(),
    )
    mocks.save_report.side_effect = OSError("disk unavailable")

    result = main_module.main([])

    assert result == 1
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.error_stage == "save"
    assert run_record.curated_item_count == 2
    assert run_record.report_path is None
    assert run_record.api_totals.logical_call_count == 3


def test_run_record_save_failure_does_not_fail_successful_report(
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
    mocks.save_run_record.side_effect = OSError("telemetry disk unavailable")

    result = main_module.main([])

    assert result == 0
    assert mocks.save_run_record.call_count == 1
    assert "Warning: Could not save run telemetry" in capsys.readouterr().err
    mocks.save_report.assert_called_once()


def test_run_record_save_failure_does_not_replace_primary_failure(
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
    mocks.curate.side_effect = CuratorError("primary curation failure")
    mocks.save_run_record.side_effect = OSError("telemetry disk unavailable")

    result = main_module.main([])

    assert result == 1
    assert mocks.save_run_record.call_count == 1
    error_output = capsys.readouterr().err
    assert "primary curation failure" in error_output
    assert "Warning: Could not save run telemetry" in error_output
    mocks.generate.assert_not_called()


def test_incomplete_usage_is_null_and_cli_does_not_print_partial_total(
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
    make_stages_call_api(
        mocks,
        api_response(10, 2, 12),
        api_response(include_usage=False),
        api_response(30, 4, 34),
    )

    result = main_module.main([])

    assert result == 0
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.api_totals.usage_complete is False
    assert run_record.api_totals.input_tokens is None
    assert run_record.api_totals.output_tokens is None
    assert run_record.api_totals.total_tokens is None
    output = capsys.readouterr().out
    assert "Tokens: incomplete telemetry" in output
    assert "Tokens: 46" not in output


def _titles(research_run: ResearchRun) -> list[str]:
    return [
        item.title
        for category in research_run.categories
        for item in category.items
    ]
