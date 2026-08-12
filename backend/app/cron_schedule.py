from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CronExpressionError(ValueError):
    pass


def _field_values(
    field: str, minimum: int, maximum: int, *, sunday_alias: bool = False
) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        base, separator, step_text = part.partition("/")
        try:
            step = int(step_text) if separator else 1
        except ValueError as exc:
            raise CronExpressionError("Cron step must be an integer") from exc
        if step < 1:
            raise CronExpressionError("Cron step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            try:
                start, end = int(start_text), int(end_text)
            except ValueError as exc:
                raise CronExpressionError("Cron range must contain integers") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronExpressionError("Cron value must be an integer") from exc
        allowed_maximum = 7 if sunday_alias else maximum
        if start < minimum or end > allowed_maximum or start > end:
            raise CronExpressionError(
                f"Cron value must be between {minimum} and {allowed_maximum}"
            )
        values.update(range(start, end + 1, step))
    if sunday_alias and 7 in values:
        values.remove(7)
        values.add(0)
    return values


def parse_cron_expression(expression: str) -> tuple[set[int], ...]:
    fields = expression.strip().split()
    if len(fields) != 5:
        raise CronExpressionError(
            "Cron expression must contain minute, hour, day, month, and weekday"
        )
    return (
        _field_values(fields[0], 0, 59),
        _field_values(fields[1], 0, 23),
        _field_values(fields[2], 1, 31),
        _field_values(fields[3], 1, 12),
        _field_values(fields[4], 0, 6, sunday_alias=True),
    )


def validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise CronExpressionError("Timezone must be a valid IANA timezone") from exc
    return timezone_name


def next_cron_run(expression: str, after: datetime, timezone_name: str) -> datetime:
    minute, hour, day, month, weekday = parse_cron_expression(expression)
    timezone = ZoneInfo(validate_timezone(timezone_name))
    after_utc = after.astimezone(UTC) if after.tzinfo else after.replace(tzinfo=UTC)
    candidate = after_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    day_is_wildcard = expression.split()[2] == "*"
    weekday_is_wildcard = expression.split()[4] == "*"
    # Five years includes leap-day expressions without accepting an expression
    # that can never produce a valid calendar date.
    for _ in range(5 * 366 * 24 * 60):
        local = candidate.astimezone(timezone)
        cron_weekday = (local.weekday() + 1) % 7
        day_matches = local.day in day
        weekday_matches = cron_weekday in weekday
        if day_is_wildcard:
            calendar_day_matches = weekday_matches
        elif weekday_is_wildcard:
            calendar_day_matches = day_matches
        else:
            calendar_day_matches = day_matches or weekday_matches
        if (
            local.minute in minute
            and local.hour in hour
            and local.month in month
            and calendar_day_matches
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise CronExpressionError("Cron expression has no run time within five years")
