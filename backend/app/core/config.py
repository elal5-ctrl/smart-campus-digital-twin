from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Smart Campus Platform API"
    version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = Field(min_length=1)
    database_connect_timeout_seconds: int = 5
    database_lock_timeout_ms: int = 5_000
    database_statement_timeout_ms: int = 30_000
    backend_cors_origins: list[str] = Field(default_factory=list)
    google_sheet_gid: str = ""
    weather_enabled: bool = True
    weather_latitude: float = 34.8102
    weather_longitude: float = 135.5616
    weather_timezone: str = "Asia/Tokyo"
    weather_poll_minutes: int = 30
    weather_retention_rows: int = 300
    synthetic_generation_enabled: bool = True
    synthetic_generation_days: int = 7
    synthetic_generation_version: str = "entries-jst-15m-v9"
    synthetic_demo_loop_enabled: bool = False
    synthetic_retention_days: int = 7
    predictions_enabled: bool = True
    predictions_poll_minutes: int = 30
    predictions_horizon_hours: int = 2
    predictions_retention_rows: int = 5000
    predictions_retention_days: int = 2
    predictions_model_version: str = "synthetic-fourier-weather-jst-v8"
    predictions_fourier_harmonics: int = 6
    predictions_fourier_ridge_alpha: float = 1.0
    predictions_fourier_minimum_samples: int = 26
    predictions_sunny_boost: float = 0.08
    predictions_rainy_penalty: float = 0.20
    people_display_enabled: bool = True
    people_display_poll_minutes: int = 5
    mqtt_publish_weather: bool = True
    mqtt_publish_people_display: bool = True
    mqtt_publish_model_state: bool = True
    mqtt_subscribe_measurements: bool = True
    mqtt_subscribe_thermal_image: bool = True
    team_b_measurements_feed_operational_counts: bool = False
    team_b_measurement_retention_days: int = 7
    team_b_measurement_freshness_minutes: int = 15
    thermal_image_max_bytes: int = 5_242_880
    thermal_image_freshness_seconds: int = 15
    mqtt_host: str = "130.149.234.145"
    mqtt_port: int = 1883
    mqtt_client_id: str = "team-a-backend"
    mqtt_topic_prefix: str = "team-b/model"
    mqtt_measurements_topic: str = "team-b/thermal/people_count"
    mqtt_thermal_image_topic: str = "team-b/thermal/image/web"


@lru_cache
def get_settings() -> Settings:
    return Settings()
