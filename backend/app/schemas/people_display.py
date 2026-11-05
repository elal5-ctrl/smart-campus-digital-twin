from pydantic import BaseModel, ConfigDict


class PeopleDisplayPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str | None
    current_count: int
    forecast_1h: int
    confidence: int | None


class PeopleDisplayMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    payload: PeopleDisplayPayload
    timestamp: int


class PeopleDisplayPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    mqtt_published: bool
    message: PeopleDisplayMessage
