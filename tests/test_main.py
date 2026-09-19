import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

import pytest

import ai_weekly_agent.main as main_module
import ai_weekly_agent.curate as curate_module
import ai_weekly_agent.report as report_module
import ai_weekly_agent.research as research_module
from ai_weekly_agent.config import AppConfig
from ai_weekly_agent.curate import CuratorError
from ai_weekly_agent.models import (
    CategoryResearchResult,
    CuratedItem,
    DateRange,
    FactSupport,
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
from ai_weekly_agent.verify import VerificationError, verify_research_run


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
                fact_support=FactSupport(
                    summary=True, technical_detail_indices=[0], benchmark=False,
                ),
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

    def research(
        *_args: object,
        client_for_category: object,
    ) -> ResearchRun:
        for category in RESEARCH_CATEGORIES:
            client_for_category(category).responses.parse(
                model=CONFIG.openai_model
            )
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
    mocks.research.assert_called_once_with(
        DATE_RANGE,
        CONFIG,
        client_for_category=ANY,
    )


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
    mocks.research.assert_called_once_with(
        expected,
        CONFIG,
        client_for_category=ANY,
    )


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
    mocks.research.assert_called_once_with(
        DATE_RANGE,
        CONFIG,
        client_for_category=ANY,
    )


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


def test_help_exits_successfully_without_loading_config_or_creating_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_pipeline(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--help"])

    assert exc_info.value.code == 0
    assert "usage: ai-weekly" in capsys.readouterr().out
    mocks.load_config.assert_not_called()
    mocks.create_client.assert_not_called()
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
        lambda research_run, **kwargs: (
            events("verify"),
            real_verify(research_run, **kwargs),
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


def test_main_creates_one_base_client_and_eight_shared_observed_views(
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
    observations: list[tuple[object, object, str, str | None, object]] = []

    def observe(
        base_client: object,
        recorder: object,
        stage: str,
        *,
        research_category: str | None = None,
    ) -> object:
        view = real_observe(
            base_client,
            recorder,
            stage,
            research_category=research_category,
        )
        observations.append(
            (base_client, recorder, stage, research_category, view)
        )
        return view

    monkeypatch.setattr(main_module, "observe_openai_client", observe)

    research_views: list[object] = []

    def research(
        *_args: object,
        client_for_category: object,
    ) -> ResearchRun:
        research_views.extend(
            client_for_category(category) for category in RESEARCH_CATEGORIES
        )
        return mocks.run

    mocks.research.side_effect = research

    result = main_module.main([])

    assert result == 0
    mocks.create_client.assert_called_once_with(CONFIG)
    assert [entry[2] for entry in observations] == [
        *("research" for _ in RESEARCH_CATEGORIES),
        "curate",
        "report",
    ]
    assert [entry[3] for entry in observations] == [
        *RESEARCH_CATEGORIES,
        None,
        None,
    ]
    assert all(entry[0] is mocks.base_client for entry in observations)
    assert len({id(entry[1]) for entry in observations}) == 1
    assert research_views == [entry[4] for entry in observations[:6]]
    assert mocks.curate.call_args.kwargs["client"] is observations[6][4]
    assert mocks.generate.call_args.kwargs["client"] is observations[7][4]


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

    def verify(run: ResearchRun, **kwargs: object) -> object:
        events.append("verify")
        return real_verify(run, **kwargs)

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
    assert run_record.verification_warning_count == 1  # Unknown date only.
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
        api_response(10, 2, 12),
        api_response(10, 2, 12),
        api_response(10, 2, 12),
        api_response(10, 2, 12),
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
        *("research" for _ in RESEARCH_CATEGORIES),
        "curate",
        "report",
    ]
    assert [record.research_category for record in run_record.api_calls] == [
        *RESEARCH_CATEGORIES,
        None,
        None,
    ]
    assert run_record.api_totals.logical_call_count == 8
    assert run_record.api_totals.total_tokens == 129
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
    assert "API calls: 8" in output
    assert "Tokens: 129" in output


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
    mocks.base_client.responses.parse.side_effect = [
        api_response(),
        api_response(),
        provider_error,
    ]

    def fail_research(
        *_args: object,
        client_for_category: object,
    ) -> ResearchRun:
        for category in RESEARCH_CATEGORIES:
            try:
                client_for_category(category).responses.parse(
                    model=CONFIG.openai_model
                )
            except RuntimeError as exc:
                raise ResearchError("research failed") from exc
        raise AssertionError("unreachable")

    mocks.research.side_effect = fail_research

    result = main_module.main([])

    assert result == 1
    run_record = mocks.save_run_record.call_args.args[0]
    assert run_record.status == "failed"
    assert run_record.error_stage == "research"
    assert [record.stage for record in run_record.api_calls] == [
        "research",
        "research",
        "research",
    ]
    assert [record.research_category for record in run_record.api_calls] == [
        *RESEARCH_CATEGORIES[:3]
    ]
    assert [record.status for record in run_record.api_calls] == [
        "success",
        "success",
        "failed",
    ]
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
        *(api_response() for _ in RESEARCH_CATEGORIES),
        RuntimeError("provider failed"),
    ]

    def research(
        *_args: object,
        client_for_category: object,
    ) -> ResearchRun:
        for category in RESEARCH_CATEGORIES:
            client_for_category(category).responses.parse(
                model=CONFIG.openai_model
            )
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
    assert [record.stage for record in run_record.api_calls] == [
        *("research" for _ in RESEARCH_CATEGORIES),
        "curate",
    ]
    assert [record.research_category for record in run_record.api_calls] == [
        *RESEARCH_CATEGORIES,
        None,
    ]
    assert [record.status for record in run_record.api_calls] == [
        *("success" for _ in RESEARCH_CATEGORIES),
        "failed",
    ]
    assert run_record.api_totals.logical_call_count == 7
    assert run_record.raw_research_path == mocks.raw_path
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
        *(api_response() for _ in RESEARCH_CATEGORIES),
        api_response(),
        RuntimeError("provider failed"),
    ]

    def research(
        *_args: object,
        client_for_category: object,
    ) -> ResearchRun:
        for category in RESEARCH_CATEGORIES:
            client_for_category(category).responses.parse(
                model=CONFIG.openai_model
            )
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
        *("research" for _ in RESEARCH_CATEGORIES),
        "curate",
        "report",
    ]
    assert [record.research_category for record in run_record.api_calls] == [
        *RESEARCH_CATEGORIES,
        None,
        None,
    ]
    assert run_record.api_totals.logical_call_count == 8
    assert run_record.api_calls[-1].status == "failed"
    assert run_record.curated_item_count == 2
    assert run_record.raw_research_path == mocks.raw_path
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
        api_response(),
        api_response(),
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
    assert run_record.api_totals.logical_call_count == 8


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
        api_response(10, 2, 12),
        api_response(10, 2, 12),
        api_response(10, 2, 12),
        api_response(10, 2, 12),
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


def curation_assessment(
    candidate_id: str, *, duplicate_of: str | None = None, score: int = 4,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "impact": score,
        "technical_significance": score,
        "novelty": score,
        "student_relevance": score,
        "semantic_duplicate_of": duplicate_of,
    }


def report_content() -> dict:
    return {
        "story_explanations": [{
            "story_id": "story_001",
            "what_it_is": "A student-friendly explanation of the development.",
            "why_it_matters": "It illustrates an important engineering tradeoff.",
            "student_takeaway": "Learn the underlying system design concepts.",
        }],
        "concepts": [{
            "name": "Engineering tradeoffs",
            "explanation": "Compare system properties under stated conditions.",
            "related_story_ids": ["story_001"],
        }],
    }


def category_run(*items: NewsItem) -> ResearchRun:
    run = make_research_run()
    for item in items:
        index = RESEARCH_CATEGORIES.index(item.category)
        run.categories[index].items.append(item)
    return run


def install_responses_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run: ResearchRun,
    *,
    assessments: list[dict] | None = None,
    content: dict | None = None,
    config: AppConfig = CONFIG,
) -> SimpleNamespace:
    """Keep real stages/persistence; fake only config and Responses transport."""
    responses: list[object] = []
    for group in run.categories:
        response = api_response()
        response.output_parsed = group.model_dump(mode="json")
        response.output = [{
            "type": "web_search_call",
            "status": "completed",
            "action": {"sources": [
                {"url": source.url}
                for item in group.items for source in item.sources
            ]},
        }]
        responses.append(response)
    for output in (
        {"assessments": assessments if assessments is not None else [
            curation_assessment("candidate_001")
        ]},
        content if content is not None else report_content(),
    ):
        response = api_response()
        response.output_parsed = output
        responses.append(response)
    parse = Mock(side_effect=responses)
    base_client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    factory = Mock(return_value=base_client)
    observe = Mock(wraps=main_module.observe_openai_client)
    verify = Mock(wraps=main_module.verify_research_run)
    curate = Mock(wraps=main_module.curate_research_run)
    generate = Mock(wraps=main_module.generate_report)
    save_raw = Mock(wraps=main_module.save_research_run)
    monkeypatch.setattr(main_module, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(main_module, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(main_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main_module, "load_config", Mock(return_value=config))
    monkeypatch.setattr(main_module, "create_openai_client", factory)
    monkeypatch.setattr(main_module, "observe_openai_client", observe)
    monkeypatch.setattr(main_module, "verify_research_run", verify)
    monkeypatch.setattr(main_module, "curate_research_run", curate)
    monkeypatch.setattr(main_module, "generate_report", generate)
    monkeypatch.setattr(main_module, "save_research_run", save_raw)
    # A stage fallback would violate the shared-client invariant and could make
    # a live request. Fail immediately if any stage attempts it.
    for module in (research_module, curate_module, report_module):
        monkeypatch.setattr(module, "create_openai_client", Mock(
            side_effect=AssertionError("stage must use injected fake client")
        ))
    return SimpleNamespace(
        parse=parse, responses=responses, factory=factory, base_client=base_client,
        observe=observe, verify=verify, curate=curate, generate=generate,
        save_raw=save_raw,
    )


def run_fresh_main() -> int:
    return main_module.main(["--start", "2026-09-01", "--end", "2026-09-07"])


def saved_record(tmp_path: Path) -> RunRecord:
    path = tmp_path / "runs" / "2026-09-01_to_2026-09-07.json"
    return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))


def saved_raw(tmp_path: Path) -> ResearchRun:
    path = tmp_path / "raw" / "2026-09-01_to_2026-09-07.json"
    return ResearchRun.model_validate_json(path.read_text(encoding="utf-8"))


def test_real_fresh_pipeline_requires_provenance_and_preserves_eight_call_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    item = make_item(1)
    item.benchmark_information = "Company-reported: 10 units on a stated setup."
    item.sources[0].evidence_roles.append("benchmark")
    item.sources[0].fact_support.benchmark = True
    item.sources.append(Source(
        title="Current background", url="https://example.com/context",
        source_type="official", evidence_roles=["background"],
        fact_support=FactSupport(
            summary=False, technical_detail_indices=[], benchmark=False,
        ),
    ))
    run = make_research_run(item)
    snapshot = run.model_dump(mode="json")
    config = AppConfig(
        openai_api_key="test-key", openai_model="test-model",
        openai_max_retries=0, openai_timeout_seconds=12.5,
    )
    mocks = install_responses_pipeline(monkeypatch, tmp_path, run, config=config)

    assert run_fresh_main() == 0

    checkpoint = mocks.verify.call_args.args[0]
    mocks.verify.assert_called_once_with(checkpoint, require_provenance=True)
    assert checkpoint.model_dump(mode="json") == snapshot
    assert saved_raw(tmp_path).model_dump(mode="json") == snapshot
    assert run.model_dump(mode="json") == snapshot
    assert _titles(mocks.curate.call_args.args[0]) == [item.title]
    selected = mocks.generate.call_args.args[1]
    assert selected[0].item.model_dump(mode="json") == item.model_dump(mode="json")
    mocks.factory.assert_called_once_with(config)
    views = mocks.observe.call_args_list
    assert len(views) == 8
    assert all(view.args[0] is mocks.base_client for view in views)
    assert len({id(view.args[1]) for view in views}) == 1
    assert [view.args[2] for view in views] == ["research"] * 6 + ["curate", "report"]
    calls = mocks.parse.call_args_list
    assert len(calls) == 8
    for call_ in calls[:6]:
        assert call_.kwargs["tools"] == [{"type": "web_search"}]
        assert call_.kwargs["max_tool_calls"] == 4
        assert call_.kwargs["text_format"] is CategoryResearchResult
    assert all("tools" not in call_.kwargs for call_ in calls[6:])
    assert calls[6].kwargs["text_format"].__name__ == "_CurationResponse"
    assert all(call_.kwargs["model"] == config.openai_model for call_ in calls)
    report_prompt = calls[7].kwargs["input"]
    assert "fact_support" not in report_prompt
    assert "evidence_roles" not in report_prompt
    assert calls[7].kwargs["text_format"] is report_module.ReportContent
    record = saved_record(tmp_path)
    assert record.schema_version == 1
    assert record.application_version == main_module.__version__ == "0.4.0"
    assert record.status == "success" and record.error_stage is None
    assert record.max_retries == 0 and record.timeout_seconds == 12.5
    assert record.researched_category_count == 6
    assert record.researched_candidate_count == record.verification_accepted_count == 1
    assert record.verification_rejected_count == record.verification_warning_count == 0
    assert record.curated_item_count == 1
    assert [entry.research_category for entry in record.api_calls] == [
        *RESEARCH_CATEGORIES, None, None,
    ]
    assert all(entry.status == "success" for entry in record.api_calls)
    assert record.api_totals.logical_call_count == 8
    assert record.api_totals.usage_complete is True
    assert record.api_totals.input_tokens == 80
    assert record.api_totals.output_tokens == 40
    assert record.api_totals.total_tokens == 120
    assert record.raw_research_path.is_file() and record.report_path.is_file()
    markdown = record.report_path.read_text(encoding="utf-8")
    for fact in (
        item.title, item.organization, item.published_date.isoformat(), item.summary,
        item.technical_details[0], item.benchmark_information,
        *(source.url for source in item.sources),
    ):
        assert fact in markdown
    assert "## This Week at a Glance" in markdown
    assert (
        f"- **{item.published_date.isoformat()} — {item.organization}:** {item.title}"
        in markdown
    )
    assert "fact_support" not in markdown


@pytest.mark.parametrize(
    "failure",
    ["legacy", "partial", "background", "summary", "date", "detail", "benchmark"],
)
def test_real_fresh_pipeline_rejects_unsupported_item_but_preserves_raw(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    accepted, rejected = make_item(1), make_item(2)
    source = rejected.sources[0]
    if failure == "legacy":
        source.fact_support = None
    elif failure in {"partial", "background"}:
        rejected.sources.append(Source(
            title="Legacy context", url="https://example.com/context",
            source_type="secondary", evidence_roles=["background"],
        ))
        if failure == "partial":
            rejected.sources[-1].evidence_roles = ["event"]
    elif failure == "summary":
        source.fact_support.summary = False
    elif failure == "date":
        source.evidence_roles.remove("event_date")
    elif failure == "detail":
        source.fact_support.technical_detail_indices = []
    elif failure == "benchmark":
        rejected.benchmark_information = "Unsupported benchmark text."
        source.evidence_roles.append("benchmark")  # Role alone is insufficient.
    run = make_research_run(accepted, rejected)
    snapshot = run.model_dump(mode="json")
    mocks = install_responses_pipeline(monkeypatch, tmp_path, run)

    assert run_fresh_main() == 0

    assert saved_raw(tmp_path).model_dump(mode="json") == snapshot
    assert run.model_dump(mode="json") == snapshot
    assert _titles(mocks.curate.call_args.args[0]) == [accepted.title]
    selected_titles = [item.item.title for item in mocks.generate.call_args.args[1]]
    assert selected_titles == [accepted.title]
    record = saved_record(tmp_path)
    assert record.researched_candidate_count == 2
    assert record.verification_accepted_count == record.verification_rejected_count == 1
    assert record.curated_item_count == 1
    assert record.status == "success"
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 8
    assert record.verification_warning_count == 0
    assert rejected.title not in record.report_path.read_text(encoding="utf-8")


def test_real_pipeline_cross_category_dedup_preserves_verify_count_and_winner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    first, winner = make_item(1), make_item(2)
    first.title = "Qualcomm Amazon announcement"
    first.organization = "Qualcomm Technologies and Amazon"
    winner.title = "Qualcomm AWS custom silicon collaboration"
    winner.category = RESEARCH_CATEGORIES[3]
    winner.organization = "Qualcomm Technologies and Amazon Web Services"
    winner.published_date = first.published_date
    winner.sources[0].url = first.sources[0].url
    winner.sources.append(Source(
        title="Winner specification", url="https://example.com/specification",
        source_type="official", evidence_roles=["technical"],
        fact_support=FactSupport(
            summary=False, technical_detail_indices=[0], benchmark=False,
        ),
    ))
    run = category_run(first, winner)
    snapshot = run.model_dump(mode="json")
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, run,
        assessments=[curation_assessment("candidate_002")],
    )

    assert run_fresh_main() == 0

    assert saved_raw(tmp_path).model_dump(mode="json") == snapshot
    assert _titles(mocks.curate.call_args.args[0]) == [first.title, winner.title]
    prompt = mocks.parse.call_args_list[6].kwargs["input"]
    assert '"candidate_id": "candidate_001"' not in prompt
    assert '"candidate_id": "candidate_002"' in prompt
    selected = mocks.generate.call_args.args[1]
    assert len(selected) == 1
    assert selected[0].item.model_dump(mode="json") == winner.model_dump(mode="json")
    assert run.model_dump(mode="json") == snapshot
    record = saved_record(tmp_path)
    assert record.researched_candidate_count == record.verification_accepted_count == 2
    assert record.verification_rejected_count == 0
    assert record.curated_item_count == 1
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 8
    assert "dedup" not in record.model_dump_json()
    markdown = record.report_path.read_text(encoding="utf-8")
    assert first.title not in markdown and first.summary not in markdown
    assert first.sources[0].title not in markdown
    for value in (
        winner.title, winner.organization, winner.summary,
        winner.technical_details[0], winner.sources[-1].url,
    ):
        assert value in markdown


def test_real_pipeline_unresolved_exact_duplicates_use_one_semantic_assessment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    first, second = make_item(1), make_item(2)
    second.published_date = first.published_date
    # Different URLs/titles survive local identity; the one model call identifies
    # semantic equivalence, and the higher-scoring complete record wins.
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(first, second),
        assessments=[
            curation_assessment("candidate_001", duplicate_of="candidate_002"),
            curation_assessment("candidate_002", score=5),
        ],
    )

    assert run_fresh_main() == 0

    prompt = mocks.parse.call_args_list[6].kwargs["input"]
    for candidate_id in ("candidate_001", "candidate_002"):
        assert f'"candidate_id": "{candidate_id}"' in prompt
    selected = mocks.generate.call_args.args[1]
    assert len(selected) == 1 and selected[0].item == second
    assert selected[0].final_score == 5
    record = saved_record(tmp_path)
    assert record.verification_accepted_count == 2
    assert record.curated_item_count == 1
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 8


@pytest.mark.parametrize("legacy_shape", ["v0.1", "v0.2", "v0.3"])
def test_legacy_json_standalone_compatibility_remains_but_fresh_main_is_strict(
    legacy_shape: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    payload = make_research_run(make_item(1)).model_dump(mode="json")
    source = payload["categories"][0]["items"][0]["sources"][0]
    source.pop("fact_support")
    if legacy_shape == "v0.1":
        source.pop("evidence_roles")
    elif legacy_shape == "v0.2":
        source["fact_support"] = None  # Explicit null also parses compatibly.
    old_json = json.dumps(payload)
    old_run = ResearchRun.model_validate_json(old_json)
    snapshot = old_run.model_dump(mode="json")
    historical_result = verify_research_run(old_run)
    assert _titles(historical_result.accepted_run) == ["Story 1"]
    assert any(
        finding.code == "legacy_fact_support"
        for finding in historical_result.findings
    )
    mocks = install_responses_pipeline(monkeypatch, tmp_path, old_run)

    assert run_fresh_main() == 0

    assert saved_raw(tmp_path).model_dump(mode="json") == snapshot
    assert old_run.model_dump(mode="json") == snapshot
    assert _titles(mocks.curate.call_args.args[0]) == []
    assert mocks.generate.call_args.args[1] == []
    assert mocks.verify.call_args.kwargs == {"require_provenance": True}
    record = saved_record(tmp_path)
    assert record.status == "success" and record.error_stage is None
    assert record.researched_candidate_count == record.verification_rejected_count == 1
    assert record.verification_accepted_count == record.curated_item_count == 0
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 6
    assert [entry.research_category for entry in record.api_calls] == list(
        RESEARCH_CATEGORIES
    )
    assert record.verification_warning_count == 0  # No compatibility fallback.
    assert "No stories passed" in record.report_path.read_text(encoding="utf-8")
    assert record.raw_research_path.is_file()


@pytest.mark.parametrize(
    "empty_kind", ["no_research", "all_rejected", "below_threshold"],
)
def test_real_empty_pipeline_counts_are_truthful_without_report_request(
    empty_kind: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    item = make_item(1)
    run = (
        make_research_run() if empty_kind == "no_research"
        else make_research_run(item)
    )
    if empty_kind == "all_rejected":
        item.sources[0].fact_support.summary = False
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, run,
        assessments=[curation_assessment("candidate_001", score=3)],
    )

    assert run_fresh_main() == 0

    record = saved_record(tmp_path)
    expected_calls = 7 if empty_kind == "below_threshold" else 6
    assert record.api_totals.logical_call_count == expected_calls
    assert mocks.parse.call_count == expected_calls
    assert record.researched_candidate_count == (
        0 if empty_kind == "no_research" else 1
    )
    assert record.verification_accepted_count == (
        1 if empty_kind == "below_threshold" else 0
    )
    assert record.verification_rejected_count == (
        1 if empty_kind == "all_rejected" else 0
    )
    assert record.curated_item_count == 0
    assert mocks.generate.call_args.args[1] == []
    assert all(entry.stage != "report" for entry in record.api_calls)
    assert record.schema_version == 1 and record.status == "success"
    assert record.api_totals.usage_complete is True
    assert record.api_totals.total_tokens == 15 * expected_calls
    assert saved_raw(tmp_path) == run
    assert record.raw_research_path.is_file() and record.report_path.is_file()
    assert "No stories passed" in record.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("missing_index", [0, 6, 7])
def test_real_pipeline_missing_usage_never_becomes_zero_or_partial_total(
    missing_index: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(make_item(1)),
    )
    mocks.responses[missing_index].usage = None

    assert run_fresh_main() == 0

    record = saved_record(tmp_path)
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 8
    assert record.api_totals.usage_complete is False
    assert record.api_totals.input_tokens is None
    assert record.api_totals.output_tokens is None
    assert record.api_totals.total_tokens is None
    assert record.api_calls[missing_index].total_tokens is None
    assert all(
        entry.total_tokens == 15
        for index, entry in enumerate(record.api_calls) if index != missing_index
    )
    assert "Tokens: incomplete telemetry" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("failure", "expected_stage", "call_count", "accepted", "curated"),
    [
        ("research", "research", 3, None, None),
        ("raw_save", "save", 6, None, None),
        ("curate", "curate", 7, 1, None),
        ("report", "report", 8, 1, 1),
        ("report_save", "save", 8, 1, 1),
    ],
)
def test_real_strict_pipeline_failures_preserve_partial_paths_counts_and_calls(
    failure: str, expected_stage: str, call_count: int,
    accepted: int | None, curated: int | None,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(make_item(1)),
    )
    failure_index = {"research": 2, "curate": 6, "report": 7}.get(failure)
    if failure_index is not None:
        mocks.responses[failure_index] = RuntimeError("fake provider failure")
        mocks.parse.side_effect = mocks.responses
    elif failure == "raw_save":
        mocks.save_raw.side_effect = OSError("fake raw disk failure")
    else:
        monkeypatch.setattr(main_module, "save_report", Mock(
            side_effect=OSError("fake report disk failure")
        ))

    assert run_fresh_main() == 1

    record = saved_record(tmp_path)
    assert record.status == "failed" and record.error_stage == expected_stage
    assert record.schema_version == 1 and record.application_version == "0.4.0"
    assert record.api_totals.logical_call_count == mocks.parse.call_count == call_count
    assert record.verification_accepted_count == accepted
    assert record.curated_item_count == curated
    assert record.report_path is None
    if failure in {"research", "raw_save"}:
        assert record.raw_research_path is None
    else:
        assert record.raw_research_path.is_file()
    if failure == "research":
        assert record.researched_candidate_count is None
        assert record.api_calls[-1].research_category == RESEARCH_CATEGORIES[2]
        mocks.curate.assert_not_called()
    else:
        assert record.researched_category_count == 6
        assert record.researched_candidate_count == 1
        assert [entry.research_category for entry in record.api_calls[:6]] == list(
            RESEARCH_CATEGORIES
        )
        assert all(entry.research_category is None for entry in record.api_calls[6:])
    if failure_index is not None:
        assert record.api_calls[-1].status == "failed"
        assert record.api_totals.usage_complete is False
        assert record.api_totals.total_tokens is None
    else:
        assert all(entry.status == "success" for entry in record.api_calls)
    if accepted is None:
        assert record.verification_rejected_count is None
        mocks.generate.assert_not_called()
    else:
        assert record.verification_rejected_count == 0
        raw_source = saved_raw(tmp_path).categories[0].items[0].sources[0]
        assert raw_source.fact_support is not None
    if curated is None:
        mocks.generate.assert_not_called()


@pytest.mark.parametrize("primary_failure", [False, True])
def test_real_pipeline_run_record_failure_is_best_effort(
    primary_failure: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(make_item(1)),
    )
    if primary_failure:
        mocks.responses[6] = RuntimeError("fake primary provider failure")
        mocks.parse.side_effect = mocks.responses
    save_record = Mock(side_effect=OSError("fake telemetry disk failure"))
    monkeypatch.setattr(main_module, "save_run_record", save_record)

    assert run_fresh_main() == (1 if primary_failure else 0)

    save_record.assert_called_once()
    record = save_record.call_args.args[0]
    assert record.verification_accepted_count == 1
    assert record.raw_research_path.is_file()
    output = capsys.readouterr()
    assert "Warning: Could not save run telemetry" in output.err
    if primary_failure:
        assert "OpenAI curation request failed" in output.err
        assert record.error_stage == "curate" and record.report_path is None
        assert mocks.parse.call_count == 7
        mocks.generate.assert_not_called()
    else:
        assert record.status == "success" and record.report_path.is_file()
        assert mocks.parse.call_count == 8


@pytest.mark.parametrize(
    "malformed", ["story_id", "concept_id", "url", "factual_field"],
)
def test_real_pipeline_report_boundary_rejects_invalid_generated_content(
    malformed: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    content = report_content()
    if malformed == "story_id":
        content["story_explanations"][0]["story_id"] = "story_999"
    elif malformed == "concept_id":
        content["concepts"][0]["related_story_ids"] = ["story_999"]
    elif malformed == "url":
        content["story_explanations"][0]["student_takeaway"] = (
            "Visit https://example.com/invented"
        )
    else:
        content["story_explanations"][0]["what_happened"] = (
            "A rewritten authoritative fact."
        )
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(make_item(1)), content=content,
    )

    assert run_fresh_main() == 1

    record = saved_record(tmp_path)
    assert record.error_stage == "report" and record.report_path is None
    assert record.verification_accepted_count == record.curated_item_count == 1
    assert record.raw_research_path.is_file()
    assert record.api_totals.logical_call_count == mocks.parse.call_count == 8
    # Successful transport/parse observation is not stage consistency success.
    assert record.api_calls[-1].status == "success"


@pytest.mark.parametrize("outcome", ["success", "provider_failure", "interrupt"])
def test_backwards_run_clock_preserves_primary_outcome_without_false_record(
    outcome: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mocks = install_responses_pipeline(
        monkeypatch, tmp_path, make_research_run(make_item(1)),
    )
    started_at = datetime(2026, 9, 18, 23, 28, 45, tzinfo=UTC)
    finished_at = started_at - timedelta(seconds=1)
    clock = Mock(side_effect=[started_at, finished_at])
    monkeypatch.setattr(main_module, "_utc_now", clock)
    save_record = Mock(wraps=main_module.save_run_record)
    monkeypatch.setattr(main_module, "save_run_record", save_record)
    if outcome != "success":
        mocks.responses[6] = (
            KeyboardInterrupt() if outcome == "interrupt"
            else RuntimeError("fake primary provider failure")
        )
        mocks.parse.side_effect = mocks.responses

    expected_exit = {"success": 0, "provider_failure": 1, "interrupt": 130}[outcome]
    assert run_fresh_main() == expected_exit

    output = capsys.readouterr()
    assert "UTC clock moved backwards" in output.err
    assert started_at.isoformat() in output.err
    assert finished_at.isoformat() in output.err
    assert "RunRecord not written" in output.err
    clock.assert_has_calls([call(), call()])
    save_record.assert_not_called()
    assert not (tmp_path / "runs").exists()
    # Standalone schema validation must still reject inverted timestamps.
    with pytest.raises(ValueError, match="started_at must not be after finished_at"):
        RunRecord(
            application_version="0.4.0", date_range=DATE_RANGE,
            started_at=started_at, finished_at=finished_at, status="success",
            api_totals=main_module.TelemetryRecorder().aggregate(),
        )
    assert saved_raw(tmp_path) == make_research_run(make_item(1))
    if outcome == "success":
        assert (tmp_path / "reports" / "2026-W37.md").is_file()
        assert "API calls: 8" in output.out
        assert "Tokens: 120" in output.out
        assert "Run telemetry saved" not in output.out
    elif outcome == "provider_failure":
        assert "OpenAI curation request failed" in output.err
        assert not (tmp_path / "reports").exists()
    else:
        assert "Interrupted by user" in output.err
        assert not (tmp_path / "reports").exists()
