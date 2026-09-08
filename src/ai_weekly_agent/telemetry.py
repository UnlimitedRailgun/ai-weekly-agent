"""Lightweight, local telemetry for logical Responses API calls."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import tempfile
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from ai_weekly_agent.dates import raw_research_filename
from ai_weekly_agent.models import DateRange


ApiStage = Literal["research", "curate", "report"]
ApiCallStatus = Literal["success", "failed"]
RunStatus = Literal["success", "failed"]
RunErrorStage = Literal[
    "research",
    "verify",
    "curate",
    "report",
    "save",
    "telemetry",
]


class ApiCallRecord(BaseModel):
    """Safe operational metadata for one logical ``responses.parse`` call."""

    stage: ApiStage
    requested_model: str | None = None
    response_model: str | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime
    status: ApiCallStatus
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_type: str | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Reject aware timestamps whose offset is not UTC."""
        if value.utcoffset() != timedelta(0):
            raise ValueError("telemetry timestamps must use UTC")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "ApiCallRecord":
        if self.started_at > self.finished_at:
            raise ValueError("started_at must not be after finished_at")
        return self


class ApiUsageTotals(BaseModel):
    """Strict aggregate totals for a recorder's logical API calls."""

    logical_call_count: int = Field(ge=0)
    successful_call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool


class RunRecord(BaseModel):
    """Operational summary for one eventual CLI run, including partial runs."""

    schema_version: Literal[1] = 1
    application_version: str = Field(min_length=1)
    date_range: DateRange
    started_at: AwareDatetime
    finished_at: AwareDatetime
    status: RunStatus
    error_stage: RunErrorStage | None = None
    max_retries: int | None = Field(default=None, ge=0)
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    api_calls: list[ApiCallRecord] = Field(default_factory=list)
    api_totals: ApiUsageTotals
    researched_category_count: int | None = Field(default=None, ge=0)
    researched_candidate_count: int | None = Field(default=None, ge=0)
    verification_accepted_count: int | None = Field(default=None, ge=0)
    verification_rejected_count: int | None = Field(default=None, ge=0)
    verification_warning_count: int | None = Field(default=None, ge=0)
    verification_information_count: int | None = Field(default=None, ge=0)
    curated_item_count: int | None = Field(default=None, ge=0)
    raw_research_path: Path | None = None
    report_path: Path | None = None
    run_record_path: Path | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Reject aware timestamps whose offset is not UTC."""
        if value.utcoffset() != timedelta(0):
            raise ValueError("run timestamps must use UTC")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "RunRecord":
        if self.started_at > self.finished_at:
            raise ValueError("started_at must not be after finished_at")
        return self


class TelemetryRecorder:
    """Collect API records for one run and calculate strict token totals."""

    def __init__(self) -> None:
        self._records: list[ApiCallRecord] = []

    @property
    def records(self) -> tuple[ApiCallRecord, ...]:
        """Return a tuple of records in observed completion order."""
        return tuple(self._records)

    def record(self, api_call: ApiCallRecord) -> None:
        """Append one completed logical call record."""
        self._records.append(api_call)

    def aggregate(self) -> ApiUsageTotals:
        """Return totals, or null token totals when any usage is incomplete."""
        records = self._records
        usage_complete = all(
            record.input_tokens is not None
            and record.output_tokens is not None
            and record.total_tokens is not None
            for record in records
        )
        token_totals: dict[str, int | None]
        if usage_complete:
            token_totals = {
                "input_tokens": sum(
                    record.input_tokens
                    for record in records
                    if record.input_tokens is not None
                ),
                "output_tokens": sum(
                    record.output_tokens
                    for record in records
                    if record.output_tokens is not None
                ),
                "total_tokens": sum(
                    record.total_tokens
                    for record in records
                    if record.total_tokens is not None
                ),
            }
        else:
            token_totals = {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }

        return ApiUsageTotals(
            logical_call_count=len(records),
            successful_call_count=sum(
                record.status == "success" for record in records
            ),
            failed_call_count=sum(record.status == "failed" for record in records),
            usage_complete=usage_complete,
            **token_totals,
        )


class _ObservedResponses:
    def __init__(
        self,
        responses: Any,
        recorder: TelemetryRecorder,
        stage: ApiStage,
        clock: Callable[[], datetime],
    ) -> None:
        self._responses = responses
        self._recorder = recorder
        self._stage = stage
        self._clock = clock

    def parse(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate one logical call and record safe completion metadata."""
        started_at = self._clock()
        requested_model = _string_value(kwargs.get("model"))
        try:
            response = self._responses.parse(*args, **kwargs)
        except Exception as exc:
            self._recorder.record(
                ApiCallRecord(
                    stage=self._stage,
                    requested_model=requested_model,
                    started_at=started_at,
                    finished_at=self._clock(),
                    status="failed",
                    error_type=type(exc).__name__,
                )
            )
            raise

        usage = _value(response, "usage")
        self._recorder.record(
            ApiCallRecord(
                stage=self._stage,
                requested_model=requested_model,
                response_model=_string_value(_value(response, "model")),
                started_at=started_at,
                finished_at=self._clock(),
                status="success",
                input_tokens=_token_value(_value(usage, "input_tokens")),
                output_tokens=_token_value(_value(usage, "output_tokens")),
                total_tokens=_token_value(_value(usage, "total_tokens")),
            )
        )
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._responses, name)


class _ObservedOpenAIClient:
    def __init__(
        self,
        base_client: Any,
        recorder: TelemetryRecorder,
        stage: ApiStage,
        clock: Callable[[], datetime],
    ) -> None:
        self._base_client = base_client
        self.responses = _ObservedResponses(
            base_client.responses,
            recorder,
            stage,
            clock,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base_client, name)


def observe_openai_client(
    base_client: Any,
    recorder: TelemetryRecorder,
    stage: ApiStage,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Any:
    """Return a stage-labelled view that delegates to ``base_client``."""
    return _ObservedOpenAIClient(
        base_client,
        recorder,
        stage,
        clock or _utc_now,
    )


def run_record_filename(date_range: DateRange) -> str:
    """Return the standard date-range JSON filename for one run record."""
    return raw_research_filename(date_range)


def save_run_record(
    run_record: RunRecord,
    output_dir: str | Path = Path("data/runs"),
) -> Path:
    """Atomically save a RunRecord, propagating filesystem failures."""
    directory = Path(output_dir)
    target = directory / run_record_filename(run_record.date_range)
    temporary_path: Path | None = None

    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(run_record.model_dump_json(indent=2))
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, target)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return target


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _value(container: object, field: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(field)
    return getattr(container, field, None)


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _token_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
