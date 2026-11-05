from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.weather import WeatherReadingResponse, WeatherRefreshResponse
from app.services.weather import (
    get_latest_weather_reading,
    get_weather_history,
    refresh_weather_reading,
)

router = APIRouter(prefix="/environment", tags=["environment"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/weather/latest", response_model=WeatherReadingResponse | None)
def latest_weather(session: SessionDep) -> WeatherReadingResponse | None:
    reading = get_latest_weather_reading(session)
    if reading is None:
        return None
    return WeatherReadingResponse.model_validate(reading, from_attributes=True)


@router.get("/weather/history", response_model=list[WeatherReadingResponse])
def weather_history(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[WeatherReadingResponse]:
    return [
        WeatherReadingResponse.model_validate(reading, from_attributes=True)
        for reading in get_weather_history(session, limit=limit)
    ]


@router.post("/weather/refresh", response_model=WeatherRefreshResponse)
def refresh_weather() -> WeatherRefreshResponse:
    try:
        reading, mqtt_published = refresh_weather_reading()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weather refresh failed",
        ) from exc

    return WeatherRefreshResponse(
        status="ok",
        mqtt_published=mqtt_published,
        reading=WeatherReadingResponse.model_validate(reading, from_attributes=True),
    )
