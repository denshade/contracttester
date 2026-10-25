from datetime import datetime, timezone

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Not verified"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    month = _MONTHS[value.month - 1]
    return f"{value.day} {month} {value.year}, {value:%H:%M} UTC"
