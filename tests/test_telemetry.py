import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ValidationError

import ai_weekly_agent.telemetry as telemetry_module
from ai_weekly_agent.models import DateRange
from ai_weekly_agent.telemetry import (
    ApiCallRecord,
    HistoricalStatusCounts,
    HistoryTelemetrySummary,
    RunRecord,
    TelemetryRecorder,
    observe_openai_client,
    run_record_filename,
    save_run_record,
)


DATE_RANGE = DateRange.model_validate(
    {"start": "2026-08-30", "end": "2026-09-05"}
)
STARTED_AT = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 8, 1, 1, tzinfo=UTC)


class FakeResponses:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def parse(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append({"args": args, "kwargs": kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses
        self.marker = object()


def response(
    *,
    model: str = "response-model",
    input_tokens: int | None = 10,
    output_tokens: int | None = 5,
    total_tokens: int | None = 15,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
    return SimpleNamespace(model=model, usage=usage)


def sequence_clock(*values: datetime) -> Any:
    timestamps = iter(values)
    return lambda: next(timestamps)


def make_api_call(
    *,
    stage: str = "research",
    research_category: str | None = None,
    input_tokens: int | None = 10,
    output_tokens: int | None = 5,
    total_tokens: int | None = 15,
    status: str = "success",
    error_type: str | None = None,
) -> ApiCallRecord:
    return ApiCallRecord(
        stage=stage,
        research_category=research_category,
        requested_model="requested-model",
        response_model="response-model" if status == "success" else None,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        error_type=error_type,
    )


def make_run_record(
    *,
    status: str = "success",
    application_version: str = "test-version",
    started_at: datetime = STARTED_AT,
    finished_at: datetime = FINISHED_AT,
    error_stage: str | None = None,
    max_retries: int | None = None,
    timeout_seconds: float | None = None,
    api_calls: list[ApiCallRecord] | None = None,
    history: HistoryTelemetrySummary | None = None,
) -> RunRecord:
    calls = api_calls if api_calls is not None else [make_api_call()]
    recorder = TelemetryRecorder()
    for call in calls:
        recorder.record(call)
    return RunRecord(
        application_version=application_version,
        date_range=DATE_RANGE,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error_stage=error_stage,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        api_calls=list(recorder.records),
        api_totals=recorder.aggregate(),
        researched_category_count=6 if status == "success" else None,
        researched_candidate_count=14 if status == "success" else None,
        verification_accepted_count=10 if status == "success" else None,
        verification_rejected_count=4 if status == "success" else None,
        verification_warning_count=2 if status == "success" else None,
        verification_information_count=1 if status == "success" else None,
        curated_item_count=8 if status == "success" else None,
        history=history,
        raw_research_path=(
            Path("data/raw/example.json") if status == "success" else None
        ),
        report_path=(
            Path("reports/2026-W36.md") if status == "success" else None
        ),
        run_record_path=Path("data/runs/example.json"),
    )


def test_successful_call_is_observed_without_changing_response() -> None:
    underlying_response = response()
    base_client = FakeClient(FakeResponses(underlying_response))
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        base_client,
        recorder,
        "research",
        research_category="AI model releases",
        clock=sequence_clock(STARTED_AT, FINISHED_AT),
    )

    returned = observed.responses.parse(
        model="requested-model",
        input="private prompt",
        tools=[{"type": "web_search"}],
    )

    assert returned is underlying_response
    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.stage == "research"
    assert record.research_category == "AI model releases"
    assert record.requested_model == "requested-model"
    assert record.response_model == "response-model"
    assert record.status == "success"
    assert record.input_tokens == 10
    assert record.output_tokens == 5
    assert record.total_tokens == 15
    assert record.error_type is None
    assert record.started_at == STARTED_AT
    assert record.finished_at == FINISHED_AT


def test_failed_call_is_recorded_and_original_exception_propagates() -> None:
    error = RuntimeError("sensitive provider details")
    base_client = FakeClient(FakeResponses(error))
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        base_client,
        recorder,
        "curate",
        clock=sequence_clock(STARTED_AT, FINISHED_AT),
    )

    with pytest.raises(RuntimeError) as exc_info:
        observed.responses.parse(model="requested-model", input="private prompt")

    assert exc_info.value is error
    record = recorder.records[0]
    assert record.stage == "curate"
    assert record.research_category is None
    assert record.requested_model == "requested-model"
    assert record.response_model is None
    assert record.status == "failed"
    assert record.input_tokens is None
    assert record.output_tokens is None
    assert record.total_tokens is None
    assert record.error_type == "RuntimeError"
    assert "sensitive provider details" not in record.model_dump_json()
    totals = recorder.aggregate()
    assert totals.logical_call_count == 1
    assert totals.successful_call_count == 0
    assert totals.failed_call_count == 1
    assert totals.usage_complete is False


def test_failed_research_call_records_category_without_extra_call() -> None:
    error = RuntimeError("provider failed")
    responses = FakeResponses(error)
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(responses),
        recorder,
        "research",
        research_category="AI research",
        clock=sequence_clock(STARTED_AT, FINISHED_AT),
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        observed.responses.parse(model="requested-model", input="private")

    assert len(responses.calls) == 1
    assert len(recorder.records) == 1
    assert recorder.records[0].status == "failed"
    assert recorder.records[0].research_category == "AI research"


@pytest.mark.parametrize("stage", ["curate", "report"])
def test_non_research_stage_rejects_category(stage: str) -> None:
    with pytest.raises(
        ValidationError,
        match="research_category is only valid for the research stage",
    ):
        make_api_call(stage=stage, research_category="AI research")


def test_legacy_research_call_may_omit_category() -> None:
    record = make_api_call(stage="research")

    assert record.research_category is None


def test_multiple_stage_views_share_base_client_and_recorder() -> None:
    base_client = FakeClient(
        FakeResponses(response(), response(), response())
    )
    recorder = TelemetryRecorder()
    timestamps = [
        STARTED_AT + timedelta(seconds=offset) for offset in range(6)
    ]
    clock = sequence_clock(*timestamps)
    clients = [
        observe_openai_client(base_client, recorder, stage, clock=clock)
        for stage in ("research", "curate", "report")
    ]

    for client in clients:
        assert client.marker is base_client.marker
        client.responses.parse(model="requested-model")

    assert len(base_client.responses.calls) == 3
    assert [record.stage for record in recorder.records] == [
        "research",
        "curate",
        "report",
    ]
    assert [record.research_category for record in recorder.records] == [
        None,
        None,
        None,
    ]
    totals = recorder.aggregate()
    assert totals.logical_call_count == 3
    assert totals.successful_call_count == 3
    assert totals.failed_call_count == 0


def test_one_wrapper_invocation_is_one_logical_call() -> None:
    base_responses = FakeResponses(response())
    base_client = FakeClient(base_responses)
    recorder = TelemetryRecorder()
    observed = observe_openai_client(base_client, recorder, "report")

    observed.responses.parse(model="requested-model")

    assert len(base_client.responses.calls) == 1
    assert recorder.aggregate().logical_call_count == 1


def test_complete_usage_is_summed_exactly() -> None:
    recorder = TelemetryRecorder()
    recorder.record(make_api_call(input_tokens=10, output_tokens=5, total_tokens=15))
    recorder.record(make_api_call(input_tokens=20, output_tokens=8, total_tokens=28))

    totals = recorder.aggregate()

    assert totals.input_tokens == 30
    assert totals.output_tokens == 13
    assert totals.total_tokens == 43
    assert totals.usage_complete is True


def test_zero_calls_have_known_zero_usage() -> None:
    totals = TelemetryRecorder().aggregate()

    assert totals.logical_call_count == 0
    assert totals.input_tokens == 0
    assert totals.output_tokens == 0
    assert totals.total_tokens == 0
    assert totals.usage_complete is True


def test_one_missing_usage_value_makes_all_aggregate_tokens_unknown() -> None:
    recorder = TelemetryRecorder()
    recorder.record(make_api_call())
    recorder.record(
        make_api_call(
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        )
    )

    totals = recorder.aggregate()

    assert recorder.records[1].input_tokens is None
    assert recorder.records[1].output_tokens is None
    assert recorder.records[1].total_tokens is None
    assert totals.input_tokens is None
    assert totals.output_tokens is None
    assert totals.total_tokens is None
    assert totals.usage_complete is False


def test_partial_usage_does_not_fail_successful_call_or_become_zero() -> None:
    underlying_response = response(total_tokens=None)
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(FakeResponses(underlying_response)),
        recorder,
        "research",
    )

    returned = observed.responses.parse(model="requested-model")

    assert returned is underlying_response
    assert recorder.records[0].input_tokens == 10
    assert recorder.records[0].output_tokens == 5
    assert recorder.records[0].total_tokens is None
    totals = recorder.aggregate()
    assert totals.input_tokens is None
    assert totals.output_tokens is None
    assert totals.total_tokens is None
    assert totals.usage_complete is False


def test_absent_usage_is_recorded_as_unknown() -> None:
    underlying_response = {"model": "response-model"}
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(FakeResponses(underlying_response)),
        recorder,
        "report",
    )

    assert observed.responses.parse(model="requested-model") is underlying_response
    assert recorder.records[0].input_tokens is None
    assert recorder.records[0].output_tokens is None
    assert recorder.records[0].total_tokens is None
    assert recorder.aggregate().usage_complete is False


def test_unusable_usage_values_are_unknown_without_affecting_response() -> None:
    underlying_response = {
        "model": "response-model",
        "usage": {
            "input_tokens": "10",
            "output_tokens": -1,
            "total_tokens": True,
        },
    }
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(FakeResponses(underlying_response)),
        recorder,
        "research",
    )

    assert observed.responses.parse(model="requested-model") is underlying_response
    assert recorder.records[0].input_tokens is None
    assert recorder.records[0].output_tokens is None
    assert recorder.records[0].total_tokens is None


def test_requested_model_is_optional_and_not_inferred_from_arguments() -> None:
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(FakeResponses(response())), recorder, "research"
    )

    observed.responses.parse("positional input")

    assert recorder.records[0].requested_model is None


def test_telemetry_does_not_serialize_sensitive_call_content() -> None:
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(FakeResponses(response())),
        recorder,
        "research",
        research_category="AI model releases",
    )

    observed.responses.parse(
        model="requested-model",
        input="PRIVATE_INPUT_MARKER",
        instructions="PRIVATE_INSTRUCTIONS_MARKER",
        tools=[{"description": "PRIVATE_TOOL_MARKER"}],
    )
    run_record = make_run_record(api_calls=list(recorder.records))
    serialized = run_record.model_dump_json()

    assert "PRIVATE_INPUT_MARKER" not in serialized
    assert "PRIVATE_INSTRUCTIONS_MARKER" not in serialized
    assert "PRIVATE_TOOL_MARKER" not in serialized
    assert "api_key" not in serialized
    assert recorder.records[0].research_category == "AI model releases"


def test_category_context_does_not_change_request_payload() -> None:
    responses = FakeResponses(response())
    recorder = TelemetryRecorder()
    observed = observe_openai_client(
        FakeClient(responses),
        recorder,
        "research",
        research_category="AI model releases",
    )

    observed.responses.parse(model="requested-model", input="private prompt")

    assert responses.calls == [
        {
            "args": (),
            "kwargs": {
                "model": "requested-model",
                "input": "private prompt",
            },
        }
    ]
    assert "research_category" not in responses.calls[0]["kwargs"]


def test_observed_timestamps_are_aware_utc_and_ordered() -> None:
    recorder = TelemetryRecorder()
    observe_openai_client(
        FakeClient(FakeResponses(response())), recorder, "report"
    ).responses.parse(model="requested-model")

    record = recorder.records[0]
    assert record.started_at.utcoffset() == timedelta(0)
    assert record.finished_at.utcoffset() == timedelta(0)
    assert record.started_at <= record.finished_at


def test_telemetry_models_reject_non_utc_timestamps() -> None:
    non_utc = timezone(timedelta(hours=8))
    data = make_api_call().model_dump(mode="python")
    data["started_at"] = STARTED_AT.astimezone(non_utc)

    with pytest.raises(ValidationError, match="timestamps must use UTC"):
        ApiCallRecord.model_validate(data)


def test_successful_run_record_round_trips_through_json() -> None:
    run_record = make_run_record(
        max_retries=0,
        timeout_seconds=30.5,
        api_calls=[make_api_call(research_category="AI model releases")],
    )

    restored = RunRecord.model_validate_json(run_record.model_dump_json())

    assert restored == run_record
    assert restored.status == "success"
    assert restored.researched_category_count == 6
    assert restored.report_path == Path("reports/2026-W36.md")
    assert restored.api_calls[0].research_category == "AI model releases"


def test_old_schema_v1_json_without_research_category_still_parses() -> None:
    payload = make_run_record().model_dump(mode="json")
    payload.pop("history")
    for call in payload["api_calls"]:
        call.pop("research_category", None)

    restored = RunRecord.model_validate(payload)

    assert restored.schema_version == 1
    assert restored.api_calls[0].stage == "research"
    assert restored.api_calls[0].research_category is None
    assert restored.history is None


def test_history_telemetry_summary_round_trips_without_content() -> None:
    summary = HistoryTelemetrySummary(
        load_state="partial",
        usable_run_count=3,
        reconstructed_story_count=11,
        skipped_entry_count=2,
        prepared_candidate_count=7,
        matched_current_candidate_count=2,
        validated_status_counts=HistoricalStatusCounts(
            new=3,
            follow_up=1,
            repeat=2,
            uncertain=1,
        ),
        repeats_suppressed=2,
        selected_follow_up_count=1,
    )
    record = make_run_record(history=summary)

    restored = RunRecord.model_validate_json(record.model_dump_json())

    assert restored.history == summary
    assert restored.schema_version == 1
    serialized = restored.model_dump_json()
    for forbidden in (
        "PRIVATE_TITLE",
        "PRIVATE_SUMMARY",
        "https://",
        "material_change",
        "source_url",
        "artifact_path",
    ):
        assert forbidden not in serialized


def test_history_telemetry_distinguishes_known_zero_from_not_executed() -> None:
    loaded_only = HistoryTelemetrySummary(
        load_state="complete",
        usable_run_count=1,
        reconstructed_story_count=2,
        skipped_entry_count=0,
    )
    completed = loaded_only.model_copy(
        update={
            "prepared_candidate_count": 0,
            "matched_current_candidate_count": 0,
            "validated_status_counts": None,
            "repeats_suppressed": None,
            "selected_follow_up_count": None,
        }
    )

    assert loaded_only.prepared_candidate_count is None
    assert completed.prepared_candidate_count == 0
    assert completed.matched_current_candidate_count == 0
    assert completed.validated_status_counts is None


def test_released_v04_reader_shape_ignores_additive_history_field() -> None:
    class ReleasedV04Reader(BaseModel):
        schema_version: Literal[1] = 1
        application_version: str
        date_range: DateRange
        started_at: datetime
        finished_at: datetime
        status: Literal["success", "failed"]

    record = make_run_record(
        history=HistoryTelemetrySummary(
            load_state="unavailable",
            usable_run_count=0,
            reconstructed_story_count=0,
            skipped_entry_count=1,
        )
    )
    payload = record.model_dump(mode="json")

    restored = ReleasedV04Reader.model_validate(payload)

    assert restored.schema_version == 1
    assert "history" not in restored.model_dump()


@pytest.mark.parametrize(
    "field",
    [
        "usable_run_count",
        "reconstructed_story_count",
        "skipped_entry_count",
        "prepared_candidate_count",
        "matched_current_candidate_count",
        "repeats_suppressed",
        "selected_follow_up_count",
    ],
)
def test_history_telemetry_rejects_negative_counts(field: str) -> None:
    payload: dict[str, object] = {
        "load_state": "complete",
        "usable_run_count": 1,
        "reconstructed_story_count": 1,
        "skipped_entry_count": 0,
        field: -1,
    }

    with pytest.raises(ValidationError):
        HistoryTelemetrySummary.model_validate(payload)


@pytest.mark.parametrize(
    "payload_update",
    [
        {
            "prepared_candidate_count": 1,
            "matched_current_candidate_count": 2,
        },
        {
            "prepared_candidate_count": 2,
            "validated_status_counts": {
                "new": 1, "follow_up": 0, "repeat": 0, "uncertain": 0,
            },
            "repeats_suppressed": 0,
            "selected_follow_up_count": 0,
        },
        {
            "prepared_candidate_count": 1,
            "validated_status_counts": {
                "new": 0, "follow_up": 0, "repeat": 1, "uncertain": 0,
            },
            "repeats_suppressed": 0,
            "selected_follow_up_count": 0,
        },
        {
            "prepared_candidate_count": 1,
            "repeats_suppressed": 0,
        },
    ],
)
def test_history_telemetry_rejects_inconsistent_stage_counts(
    payload_update: dict[str, object],
) -> None:
    payload = {
        "load_state": "complete",
        "usable_run_count": 1,
        "reconstructed_story_count": 2,
        "skipped_entry_count": 0,
        **payload_update,
    }

    with pytest.raises(ValidationError):
        HistoryTelemetrySummary.model_validate(payload)


def test_failed_partial_run_record_round_trips_through_json() -> None:
    failed_call = make_api_call(
        status="failed",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        error_type="RuntimeError",
    )
    run_record = make_run_record(
        status="failed",
        error_stage="curate",
        api_calls=[failed_call],
    )

    restored = RunRecord.model_validate_json(run_record.model_dump_json())

    assert restored == run_record
    assert restored.status == "failed"
    assert restored.error_stage == "curate"
    assert restored.researched_category_count is None
    assert restored.curated_item_count is None
    assert restored.report_path is None
    assert restored.api_totals.usage_complete is False


def test_run_record_distinguishes_default_retries_from_disabled_retries() -> None:
    sdk_default = make_run_record(max_retries=None)
    disabled = make_run_record(max_retries=0)

    assert sdk_default.max_retries is None
    assert disabled.max_retries == 0
    assert sdk_default.model_dump(mode="json")["max_retries"] is None
    assert disabled.model_dump(mode="json")["max_retries"] == 0


def test_run_record_filename_uses_date_range() -> None:
    assert run_record_filename(DATE_RANGE) == "2026-08-30_to_2026-09-05.json"


def test_save_run_record_creates_directory_and_valid_json(tmp_path: Path) -> None:
    output_dir = tmp_path / "nested" / "runs"
    run_record = make_run_record()

    target = save_run_record(run_record, output_dir=output_dir)

    assert target == output_dir / run_record_filename(DATE_RANGE)
    assert json.loads(target.read_text(encoding="utf-8")) == (
        run_record.model_dump(mode="json")
    )
    assert list(output_dir.glob("*.tmp")) == []


def test_save_run_record_atomically_replaces_same_date_record(
    tmp_path: Path,
) -> None:
    first = make_run_record(status="failed", error_stage="research")
    second = make_run_record(status="success")

    first_path = save_run_record(first, output_dir=tmp_path)
    second_path = save_run_record(second, output_dir=tmp_path)

    assert second_path == first_path
    assert RunRecord.model_validate_json(
        second_path.read_text(encoding="utf-8")
    ) == second


def test_failed_atomic_replace_preserves_existing_record_and_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / run_record_filename(DATE_RANGE)
    target.write_text("existing record\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(telemetry_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        save_run_record(make_run_record(), output_dir=tmp_path)

    assert target.read_text(encoding="utf-8") == "existing record\n"
    assert list(tmp_path.glob("*.tmp")) == []
