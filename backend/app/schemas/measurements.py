from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SensorType = Literal["light_barrier", "area"]
CountType = Literal["interval_count", "snapshot"]


class MeasurementSensor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: SensorType
    zone_id: str = Field(min_length=1)
    floor_level: int


class MeasurementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people_count: int = Field(ge=0)
    count_type: CountType
    interval_seconds: int | None = Field(default=None, gt=0)


class MeasurementMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    action: Literal["measurement_update"]
    source: Literal["team-b"]
    timestamp: int
    sensor: MeasurementSensor
    measurement: MeasurementPayload


class MeasurementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    received_at: datetime
    source_timestamp: datetime
    version: int
    action: str
    source: str
    sensor_id: str
    sensor_type: str
    zone_id: str
    floor_level: int
    people_count: int
    count_type: str
    interval_seconds: int | None


class MeasurementIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    measurement: MeasurementResponse
