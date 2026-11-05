from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.predictions import (
    PredictionRefreshResponse,
    TrafficPredictionResponse,
)
from app.services.predictions import (
    get_latest_predictions_by_location,
    get_prediction_history,
    refresh_traffic_predictions,
)

router = APIRouter(prefix="/predictions", tags=["predictions"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/latest", response_model=list[TrafficPredictionResponse])
def latest_predictions(session: SessionDep) -> list[TrafficPredictionResponse]:
    predictions = get_latest_predictions_by_location(session)
    return [
        TrafficPredictionResponse.model_validate(
            prediction,
            from_attributes=True,
        )
        for prediction in predictions.values()
    ]


@router.get("/history", response_model=list[TrafficPredictionResponse])
def prediction_history(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TrafficPredictionResponse]:
    return [
        TrafficPredictionResponse.model_validate(
            prediction,
            from_attributes=True,
        )
        for prediction in get_prediction_history(session, limit=limit)
    ]


@router.post("/refresh", response_model=PredictionRefreshResponse)
def refresh_predictions() -> PredictionRefreshResponse:
    try:
        rows_generated = refresh_traffic_predictions()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction refresh failed",
        ) from exc

    return PredictionRefreshResponse(status="ok", rows_generated=rows_generated)
