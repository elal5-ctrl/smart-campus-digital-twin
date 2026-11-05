from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.model_status import ModelStatusResponse
from app.schemas.people_display import (
    PeopleDisplayMessage,
    PeopleDisplayPublishResponse,
)
from app.services.model_state import (
    build_locations_payload,
    build_model_status,
    build_nodes_payload,
    publish_model_state_update,
)
from app.services.people_display import (
    build_people_display_message,
    publish_people_display_update,
)

router = APIRouter(prefix="/model", tags=["model"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/people-display/latest", response_model=PeopleDisplayMessage)
def latest_people_display(session: SessionDep) -> PeopleDisplayMessage:
    return build_people_display_message(session)


@router.get("/status", response_model=ModelStatusResponse)
def model_status(session: SessionDep) -> ModelStatusResponse:
    return build_model_status(session)


@router.post(
    "/people-display/publish",
    response_model=PeopleDisplayPublishResponse,
)
def publish_people_display() -> PeopleDisplayPublishResponse:
    try:
        message, mqtt_published = publish_people_display_update()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="People display publish failed",
        ) from exc

    return PeopleDisplayPublishResponse(
        status="ok",
        mqtt_published=mqtt_published,
        message=message,
    )


@router.get("/locations/latest")
def latest_locations(session: SessionDep):
    return build_locations_payload(session)


@router.get("/nodes/latest")
def latest_nodes(session: SessionDep):
    return build_nodes_payload(session)


@router.post("/model-state/publish")
def publish_model_state():
    try:
        locations, nodes, mqtt_published = publish_model_state_update()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model state publish failed",
        ) from exc

    return {
        "status": "ok",
        "mqtt_published": mqtt_published,
        "locations": locations,
        "nodes": nodes,
    }
