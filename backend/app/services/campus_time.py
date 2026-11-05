from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings


def campus_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().weather_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Tokyo")


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def campus_now() -> datetime:
    return datetime.now(campus_timezone())


def utc_naive_to_campus(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC).astimezone(campus_timezone())


def campus_naive_to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=campus_timezone()).astimezone(UTC).replace(tzinfo=None)
