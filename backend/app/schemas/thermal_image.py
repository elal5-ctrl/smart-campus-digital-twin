from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ThermalImageState = Literal["waiting", "live", "stale"]


class ThermalImageStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    state: ThermalImageState
    received_at: datetime | None
    media_type: str | None
    size_bytes: int | None
    revision: str | None
    topic: str
