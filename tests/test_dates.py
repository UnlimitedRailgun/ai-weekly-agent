from datetime import date

import pytest
from pydantic import ValidationError

from ai_weekly_agent.dates import (
    get_date_range_for_days,
    get_default_date_range,
    get_explicit_date_range,
    raw_research_filename,
    weekly_report_filename,
)


def test_default_range_contains_seven_inclusive_calendar_dates() -> None:
    date_range = get_default_date_range(today=date(2026, 9, 5))

    assert date_range.start == date(2026, 8, 30)
    assert date_range.end == date(2026, 9, 5)


@pytest.mark.parametrize(
    ("days", "expected_start"),
    [
        (7, date(2026, 9, 1)),
        (3, date(2026, 9, 5)),
        (1, date(2026, 9, 7)),
    ],
)
def test_relative_range_contains_requested_inclusive_calendar_dates(
    days: int,
    expected_start: date,
) -> None:
    date_range = get_date_range_for_days(days, today=date(2026, 9, 7))

    assert date_range.start == expected_start
    assert date_range.end == date(2026, 9, 7)


@pytest.mark.parametrize("days", [0, -1])
def test_relative_range_requires_positive_days(days: int) -> None:
    with pytest.raises(ValueError, match="days must be a positive integer"):
        get_date_range_for_days(days, today=date(2026, 9, 7))


def test_explicit_date_range() -> None:
    date_range = get_explicit_date_range(
        start=date(2026, 8, 1),
        end=date(2026, 8, 7),
    )

    assert date_range.start == date(2026, 8, 1)
    assert date_range.end == date(2026, 8, 7)


def test_invalid_explicit_date_range() -> None:
    with pytest.raises(ValidationError, match="start must not be after end"):
        get_explicit_date_range(
            start=date(2026, 8, 8),
            end=date(2026, 8, 7),
        )


def test_raw_research_filename() -> None:
    date_range = get_default_date_range(today=date(2026, 9, 5))

    assert raw_research_filename(date_range) == (
        "2026-08-30_to_2026-09-05.json"
    )


def test_weekly_report_filename_uses_end_date_iso_week() -> None:
    date_range = get_default_date_range(today=date(2026, 9, 5))

    assert weekly_report_filename(date_range) == "2026-W36.md"
