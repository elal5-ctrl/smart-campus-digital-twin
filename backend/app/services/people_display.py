import logging
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import Entry, SyntheticLocationMeasurement, TeamBMeasurement
from app.schemas.people_display import PeopleDisplayMessage, PeopleDisplayPayload
from app.services.campus_time import campus_now
from app.services.fixedlocations import FIXED_LOCATIONS, SENSOR_FIXED_LOCATION_MAP
from app.services.measurements import get_latest_operational_measurements_by_sensor
from app.services.mqtt import (
    people_display_topic,
    publish_people_display,
)
from app.services.mqtt_status import record_publish_attempt
from app.services.predictions import get_one_hour_prediction_total
from app.services.synthetic_data import get_latest_synthetic_measurements_by_location

PEOPLE_DISPLAY_ACTION = "update_people_display"
logger = logging.getLogger("uvicorn.error")


def build_people_display_message(session: Session) -> PeopleDisplayMessage:
    latest_measurements = get_latest_operational_measurements_by_sensor(session)
    latest_synthetic = get_latest_synthetic_measurements_by_location(session)
    if latest_measurements:
        current_count = _fixed_location_current_count(
            latest_measurements,
            latest_synthetic,
        )
        forecast_count = get_one_hour_prediction_total(session)
        return _build_people_display_message(
            current_count,
            forecast_count,
        )

    if latest_synthetic:
        current_count = sum(
            measurement.people_count for measurement in latest_synthetic.values()
        )
        forecast_count = get_one_hour_prediction_total(session)
        return _build_people_display_message(
            current_count,
            forecast_count,
        )

    latest_timestamp = session.exec(select(func.max(Entry.timestamp))).one()

    if latest_timestamp is None:
        return _build_people_display_message(0, 0)

    current_count = _current_count_at_timestamp(session, latest_timestamp)

    return _build_people_display_message(current_count, None)


def _build_people_display_message(
    current_count: int,
    forecast_count: int | None,
) -> PeopleDisplayMessage:
    display_time = campus_now()
    return PeopleDisplayMessage(
        action=PEOPLE_DISPLAY_ACTION,
        payload=PeopleDisplayPayload(
            time=display_time.strftime("%H:%M"),
            current_count=current_count,
            forecast_1h=forecast_count
            if forecast_count is not None
            else _fallback_forecast_count_1h(current_count),
            confidence=None,
        ),
        timestamp=int(display_time.timestamp()),
    )


def publish_people_display_update() -> tuple[PeopleDisplayMessage, bool]:
    with Session(engine) as session:
        message = build_people_display_message(session)

    if not get_settings().mqtt_publish_people_display:
        return message, False

    payload_source = _people_display_source(message)
    try:
        publish_people_display(message.model_dump())
    except OSError as exc:
        record_publish_attempt(
            channel="people-display",
            topic=people_display_topic(),
            success=False,
            error=str(exc),
            payload_source=payload_source,
        )
        logger.warning(
            "People display MQTT publish failed on %s: %s", people_display_topic(), exc
        )
        return message, False

    record_publish_attempt(
        channel="people-display",
        topic=people_display_topic(),
        success=True,
        payload_source=payload_source,
    )
    logger.warning(
        "Published people display update to %s: current=%s forecast_1h=%s time=%s",
        people_display_topic(),
        message.payload.current_count,
        message.payload.forecast_1h,
        message.payload.time,
    )
    return message, True


def _people_display_source(message: PeopleDisplayMessage) -> str:
    if message.payload.confidence is not None and message.payload.confidence >= 100:
        return "real"
    if message.payload.current_count > 0:
        return "simulated"
    return "empty"


def _current_count_at_timestamp(session: Session, timestamp: datetime) -> int:
    total_count = session.exec(
        select(func.sum(Entry.total_count)).where(Entry.timestamp == timestamp)
    ).one()
    return int(total_count or 0)


def _fixed_location_current_count(
    latest_measurements: list[TeamBMeasurement],
    latest_synthetic: dict[str, SyntheticLocationMeasurement],
) -> int:
    counts = {
        location.id: latest_synthetic[location.id].people_count
        for location in FIXED_LOCATIONS
        if location.id in latest_synthetic
    }
    for measurement in latest_measurements:
        location_id = SENSOR_FIXED_LOCATION_MAP.get(measurement.sensor_id)
        if location_id is not None:
            counts[location_id] = measurement.people_count
    return sum(counts.values())


def _fallback_forecast_count_1h(current_count: int) -> int:
    return current_count
