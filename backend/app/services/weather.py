import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import WeatherReading
from app.services.mqtt import publish_weather_reading, weather_topic
from app.services.mqtt_status import record_publish_attempt

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def create_weather_table() -> None:
    WeatherReading.__table__.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE weather_readings "
                "ADD COLUMN IF NOT EXISTS temp_high_c DOUBLE PRECISION"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE weather_readings "
                "ADD COLUMN IF NOT EXISTS temp_low_c DOUBLE PRECISION"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE weather_readings "
                "ADD COLUMN IF NOT EXISTS rain_chance_pct INTEGER"
            )
        )


def refresh_weather_reading() -> tuple[WeatherReading, bool]:
    mqtt_published = False
    with Session(engine) as session:
        reading = fetch_current_weather()
        existing_reading = session.exec(
            select(WeatherReading).where(
                WeatherReading.source_timestamp == reading.source_timestamp
            )
        ).first()
        if existing_reading is not None:
            _update_weather_reading(existing_reading, reading)
            reading = existing_reading
            session.add(reading)
            session.commit()
        else:
            session.add(reading)
            session.commit()
            session.refresh(reading)

        prune_weather_readings(session, get_settings().weather_retention_rows)
        session.refresh(reading)

        if get_settings().mqtt_publish_weather:
            try:
                publish_weather_reading(reading)
                mqtt_published = True
            except OSError as exc:
                record_publish_attempt(
                    channel="weather",
                    topic=weather_topic(),
                    success=False,
                    error=str(exc),
                    payload_source="weather",
                )
                mqtt_published = False
            else:
                record_publish_attempt(
                    channel="weather",
                    topic=weather_topic(),
                    success=True,
                    payload_source="weather",
                )

        return reading, mqtt_published


def fetch_current_weather() -> WeatherReading:
    settings = get_settings()
    url = _build_weather_url()
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    current = payload.get("current")
    if not isinstance(current, dict):
        raise ValueError("Weather API response does not contain current weather data")

    daily = payload.get("daily")
    if not isinstance(daily, dict):
        daily = {}

    return WeatherReading(
        source_timestamp=_parse_weather_time(current["time"]),
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
        latitude=settings.weather_latitude,
        longitude=settings.weather_longitude,
        timezone=settings.weather_timezone,
        temperature_c=float(current["temperature_2m"]),
        temp_high_c=_optional_daily_float(daily, "temperature_2m_max"),
        temp_low_c=_optional_daily_float(daily, "temperature_2m_min"),
        humidity_percent=_optional_int(current.get("relative_humidity_2m")),
        rain_chance_pct=_optional_daily_int(daily, "precipitation_probability_max"),
        precipitation_mm=_optional_float(current.get("precipitation")),
        rain_mm=_optional_float(current.get("rain")),
        wind_speed_kmh=_optional_float(current.get("wind_speed_10m")),
        weather_code=_optional_int(current.get("weather_code")),
        condition=weather_condition(_optional_int(current.get("weather_code"))),
    )


def get_latest_weather_reading(session: Session) -> WeatherReading | None:
    statement = select(WeatherReading).order_by(WeatherReading.source_timestamp.desc())
    return session.exec(statement).first()


def get_weather_history(session: Session, limit: int = 100) -> list[WeatherReading]:
    statement = (
        select(WeatherReading)
        .order_by(WeatherReading.source_timestamp.desc())
        .limit(max(1, min(limit, 500)))
    )
    return list(session.exec(statement).all())


def prune_weather_readings(session: Session, max_rows: int = 300) -> int:
    if max_rows <= 0:
        return 0

    stale_ids = list(
        session.exec(
            select(WeatherReading.id)
            .where(WeatherReading.id.is_not(None))
            .order_by(WeatherReading.source_timestamp.desc(), WeatherReading.id.desc())
            .offset(max_rows)
        ).all()
    )
    if not stale_ids:
        return 0

    session.exec(delete(WeatherReading).where(WeatherReading.id.in_(stale_ids)))
    session.commit()
    return len(stale_ids)


def _update_weather_reading(
    target: WeatherReading,
    source: WeatherReading,
) -> None:
    target.fetched_at = source.fetched_at
    target.latitude = source.latitude
    target.longitude = source.longitude
    target.timezone = source.timezone
    target.temperature_c = source.temperature_c
    target.temp_high_c = source.temp_high_c
    target.temp_low_c = source.temp_low_c
    target.humidity_percent = source.humidity_percent
    target.rain_chance_pct = source.rain_chance_pct
    target.precipitation_mm = source.precipitation_mm
    target.rain_mm = source.rain_mm
    target.wind_speed_kmh = source.wind_speed_kmh
    target.weather_code = source.weather_code
    target.condition = source.condition


def _build_weather_url() -> str:
    settings = get_settings()
    query = urlencode(
        {
            "latitude": settings.weather_latitude,
            "longitude": settings.weather_longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "rain",
                    "weather_code",
                    "wind_speed_10m",
                ]
            ),
            "daily": ",".join(
                [
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
                ]
            ),
            "timezone": settings.weather_timezone,
        }
    )
    return f"{OPEN_METEO_URL}?{query}"


def _parse_weather_time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_daily_float(daily: dict[str, Any], key: str) -> float | None:
    values = daily.get(key)
    if not isinstance(values, list) or not values:
        return None
    return _optional_float(values[0])


def _optional_daily_int(daily: dict[str, Any], key: str) -> int | None:
    values = daily.get(key)
    if not isinstance(values, list) or not values:
        return None
    return _optional_int(values[0])


def weather_condition(code: int | None) -> str | None:
    if code is None:
        return None
    if code == 0:
        return "sunny"
    if code in {1, 2, 3}:
        return "cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "unknown"
