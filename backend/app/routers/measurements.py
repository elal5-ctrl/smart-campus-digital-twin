from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.measurements import (
    MeasurementIngestResponse,
    MeasurementMessage,
    MeasurementResponse,
)
from app.services.measurements import (
    get_latest_measurement,
    get_measurement_history,
    store_measurement_message,
)

router = APIRouter(prefix="/measurements", tags=["measurements"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", response_model=MeasurementIngestResponse)
def ingest_measurement(
    message: MeasurementMessage,
    session: SessionDep,
) -> MeasurementIngestResponse:
    try:
        measurement = store_measurement_message(session, message)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Measurement ingest failed",
        ) from exc

    return MeasurementIngestResponse(
        status="ok",
        measurement=MeasurementResponse.model_validate(
            measurement,
            from_attributes=True,
        ),
    )


@router.get("/latest", response_model=MeasurementResponse | None)
def latest_measurement(session: SessionDep) -> MeasurementResponse | None:
    measurement = get_latest_measurement(session)
    if measurement is None:
        return None
    return MeasurementResponse.model_validate(measurement, from_attributes=True)


@router.get("/history", response_model=list[MeasurementResponse])
def measurement_history(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MeasurementResponse]:
    return [
        MeasurementResponse.model_validate(measurement, from_attributes=True)
        for measurement in get_measurement_history(session, limit=limit)
    ]
