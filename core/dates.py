"""Date range helpers shared by dashboards, sales filters and reports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from core.constants import Period


def start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min)


def end_of_day(day: date) -> datetime:
    """Inclusive upper bound for a day (23:59:59.999999)."""
    return datetime.combine(day, time.max)


def day_range(day: date) -> tuple[datetime, datetime]:
    return start_of_day(day), end_of_day(day)


def today_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    return day_range((now or datetime.now()).date())


def yesterday_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    return day_range((now or datetime.now()).date() - timedelta(days=1))


def week_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday of the current week through today."""
    today = (now or datetime.now()).date()
    return start_of_day(today - timedelta(days=today.weekday())), end_of_day(today)


def month_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    today = (now or datetime.now()).date()
    return start_of_day(today.replace(day=1)), end_of_day(today)


def last_days_range(days: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    """The trailing ``days`` calendar days including today."""
    today = (now or datetime.now()).date()
    return start_of_day(today - timedelta(days=days - 1)), end_of_day(today)


def custom_range(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    start = start or date.today()
    end = end or start
    if end < start:
        start, end = end, start
    return start_of_day(start), end_of_day(end)


def resolve_period(
    period: str | None,
    start: date | None = None,
    end: date | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Map a Period label (plus optional custom dates) to an inclusive range."""
    period = period or Period.TODAY
    if period == Period.TODAY:
        return today_range(now)
    if period == Period.YESTERDAY:
        return yesterday_range(now)
    if period == Period.THIS_WEEK:
        return week_range(now)
    if period == Period.THIS_MONTH:
        return month_range(now)
    if period == Period.LAST_7_DAYS:
        return last_days_range(7, now)
    if period == Period.LAST_30_DAYS:
        return last_days_range(30, now)
    if period == Period.CUSTOM:
        return custom_range(start, end)
    raise ValueError(f"Unknown period: {period!r}")


def each_day(start: datetime, end: datetime) -> list[date]:
    """Every calendar date inside a range — used to zero-fill chart series."""
    days: list[date] = []
    current = start.date()
    last = end.date()
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return days


def format_range(start: datetime, end: datetime) -> str:
    start_day, end_day = start.date(), end.date()
    if start_day == end_day:
        return start_day.strftime("%d %b %Y")
    if start_day.year == end_day.year:
        return f"{start_day.strftime('%d %b')} - {end_day.strftime('%d %b %Y')}"
    return f"{start_day.strftime('%d %b %Y')} - {end_day.strftime('%d %b %Y')}"


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%d %b %Y %H:%M") if value else ""


def format_time(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""
