"""Deterministic reporting-date and filename utilities."""

from datetime import date, timedelta

from ai_weekly_agent.models import DateRange


def get_default_date_range(today: date | None = None) -> DateRange:
    """Return seven inclusive calendar dates ending on ``today``."""
    return get_date_range_for_days(7, today=today)


def get_date_range_for_days(
    days: int,
    today: date | None = None,
) -> DateRange:
    """Return ``days`` inclusive calendar dates ending on ``today``."""
    if days <= 0:
        raise ValueError("days must be a positive integer")

    end = today if today is not None else date.today()
    return DateRange(start=end - timedelta(days=days - 1), end=end)


def get_explicit_date_range(start: date, end: date) -> DateRange:
    """Return a validated explicit inclusive date range."""
    return DateRange(start=start, end=end)


def raw_research_filename(date_range: DateRange) -> str:
    """Return the date-based JSON filename for raw research."""
    return f"{date_range.start.isoformat()}_to_{date_range.end.isoformat()}.json"


def weekly_report_filename(date_range: DateRange) -> str:
    """Return the ISO week filename based on the range end date."""
    iso_year, iso_week, _ = date_range.end.isocalendar()
    return f"{iso_year}-W{iso_week:02d}.md"
