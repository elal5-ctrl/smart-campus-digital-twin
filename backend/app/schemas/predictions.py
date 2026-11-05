from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrafficPredictionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    generated_at: datetime
    target_timestamp: datetime
    location_id: str
    location_name: str
    latitude: float
    longitude: float
    base_count: int
    predicted_count: int
    weather_adjusted_count: int
    weather_condition: str | None
    weather_multiplier: float
    model_version: str


class PredictionRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    rows_generated: int
