from typing import Literal

from pydantic import BaseModel, ConfigDict

Lang = Literal["de", "en", "ja"]
SensorKind = Literal["entry", "zone", "model"]
SensorStatus = Literal["live", "simulated", "waiting"]
HeatmapSource = Literal["live", "synthetic", "prediction"]
Priority = Literal["hoch", "mittel", "niedrig"]


class LocalizedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    de: str
    en: str
    ja: str


class SensorPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: LocalizedText
    kind: SensorKind
    measured: int
    forecast: int
    confidence: int
    position: tuple[float, float]
    status: SensorStatus


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place: LocalizedText
    reason: LocalizedText
    priority: Priority


class HeatmapPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    position: tuple[float, float]
    intensity: float
    measured: int
    forecast: int
    source: HeatmapSource


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latestTimestamp: str | None
    sensorPoints: list[SensorPoint]
    heatmapPoints: list[HeatmapPoint]
    recommendations: list[Recommendation]
    measuredHours: list[int]
    forecastHours: list[int]
