from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class Entry(SQLModel, table=True):
    __tablename__ = "entries"

    id: int | None = Field(default=None, primary_key=True)

    timestamp: datetime

    coordinates: str = Field(sa_column=Column(Geometry("POINT", srid=4326)))

    total_count: int

    level: int


class WeatherReading(SQLModel, table=True):
    __tablename__ = "weather_readings"

    id: int | None = Field(default=None, primary_key=True)

    source_timestamp: datetime = Field(index=True)

    fetched_at: datetime

    latitude: float

    longitude: float

    timezone: str

    temperature_c: float

    temp_high_c: float | None = None

    temp_low_c: float | None = None

    humidity_percent: int | None = None

    rain_chance_pct: int | None = None

    precipitation_mm: float | None = None

    rain_mm: float | None = None

    wind_speed_kmh: float | None = None

    weather_code: int | None = None

    condition: str | None = None


class Locations(SQLModel, table=True):
    __tablename__ = "locations"

    id: int | None = Field(default=None, primary_key=True)

    tracking_spots: str

    readings: int | None = None


class TeamBMeasurement(SQLModel, table=True):
    __tablename__ = "team_b_measurements"

    id: int | None = Field(default=None, primary_key=True)

    received_at: datetime = Field(index=True)

    source_timestamp: datetime = Field(index=True)

    version: int

    action: str

    source: str

    sensor_id: str = Field(index=True)

    sensor_type: str

    zone_id: str = Field(index=True)

    floor_level: int

    people_count: int

    count_type: str

    interval_seconds: int | None = None

    raw_payload: dict | None = Field(default=None, sa_column=Column(JSON))


class MqttPublishStatus(SQLModel, table=True):
    __tablename__ = "mqtt_publish_status"

    channel: str = Field(primary_key=True)

    topic: str

    attempted_at: datetime = Field(index=True)

    success: bool

    error: str | None = None

    payload_source: str


class SyntheticLocationMeasurement(SQLModel, table=True):
    __tablename__ = "synthetic_location_measurements"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "source_timestamp",
            "generation_version",
            name="uq_synth_location_timestamp_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    source_timestamp: datetime = Field(index=True)

    location_id: str = Field(index=True)

    location_name: str

    latitude: float

    longitude: float

    people_count: int

    generation_version: str = Field(index=True)

    created_at: datetime


class TrafficPrediction(SQLModel, table=True):
    __tablename__ = "traffic_predictions"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "target_timestamp",
            "model_version",
            name="uq_prediction_location_timestamp_model",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    generated_at: datetime = Field(index=True)

    target_timestamp: datetime = Field(index=True)

    location_id: str = Field(index=True)

    location_name: str

    latitude: float

    longitude: float

    base_count: int

    predicted_count: int

    weather_adjusted_count: int

    weather_condition: str | None = None

    weather_multiplier: float

    model_version: str = Field(index=True)
