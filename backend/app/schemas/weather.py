from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WeatherReadingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    source_timestamp: datetime
    fetched_at: datetime
    latitude: float
    longitude: float
    timezone: str
    temperature_c: float
    temp_high_c: float | None
    temp_low_c: float | None
    humidity_percent: int | None
    rain_chance_pct: int | None
    precipitation_mm: float | None
    rain_mm: float | None
    wind_speed_kmh: float | None
    weather_code: int | None
    condition: str | None


class WeatherRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    mqtt_published: bool
    reading: WeatherReadingResponse | None = None
