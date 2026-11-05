from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

DataMode = Literal["real", "mixed", "simulated"]


class MqttConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    topic_prefix: str
    measurements_topic: str
    thermal_image_topic: str
    publish_weather: bool
    publish_people_display: bool
    publish_model_state: bool
    subscribe_measurements: bool
    subscribe_thermal_image: bool


class LatestMeasurementSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: str
    sensor_type: str
    zone_id: str
    people_count: int
    source_timestamp: datetime
    received_at: datetime


class PublishStatusSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    topic: str
    attempted_at: datetime
    success: bool
    error: str | None
    payload_source: str


class ModelStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: DataMode
    live_sensor_count: int
    simulated_location_count: int
    latest_measurement: LatestMeasurementSummary | None
    mqtt: MqttConfigSummary
    publish_statuses: list[PublishStatusSummary]
    last_publish_error: str | None
