from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import TeamBMeasurement
from app.schemas.measurements import MeasurementMessage
from app.services.campus_time import utc_now_naive


def create_measurements_table() -> None:
    TeamBMeasurement.__table__.create(engine, checkfirst=True)


def store_measurement_message(
    session: Session,
    message: MeasurementMessage,
) -> TeamBMeasurement:
    measurement = TeamBMeasurement(
        received_at=datetime.now(UTC).replace(tzinfo=None),
        source_timestamp=datetime.fromtimestamp(message.timestamp, UTC).replace(
            tzinfo=None
        ),
        version=message.version,
        action=message.action,
        source=message.source,
        sensor_id=message.sensor.id,
        sensor_type=message.sensor.type,
        zone_id=message.sensor.zone_id,
        floor_level=message.sensor.floor_level,
        people_count=message.measurement.people_count,
        count_type=message.measurement.count_type,
        interval_seconds=message.measurement.interval_seconds,
        raw_payload=message.model_dump(),
    )

    session.add(measurement)
    session.commit()
    session.refresh(measurement)
    return measurement


def store_measurement_from_mqtt(message: MeasurementMessage) -> TeamBMeasurement:
    with Session(engine) as session:
        return store_measurement_message(session, message)


def get_latest_measurement(session: Session) -> TeamBMeasurement | None:
    statement = select(TeamBMeasurement).order_by(TeamBMeasurement.received_at.desc())
    return session.exec(statement).first()


def get_latest_measurements_by_sensor(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[TeamBMeasurement]:
    freshness_minutes = max(
        1,
        get_settings().team_b_measurement_freshness_minutes,
    )
    cutoff = (now or utc_now_naive()) - timedelta(minutes=freshness_minutes)
    statement = (
        select(TeamBMeasurement)
        .where(TeamBMeasurement.received_at >= cutoff)
        .order_by(TeamBMeasurement.received_at.desc())
    )
    measurements_by_sensor: dict[str, TeamBMeasurement] = {}
    for measurement in session.exec(statement):
        if measurement.sensor_id not in measurements_by_sensor:
            measurements_by_sensor[measurement.sensor_id] = measurement

    return list(measurements_by_sensor.values())


def get_latest_operational_measurements_by_sensor(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[TeamBMeasurement]:
    if not get_settings().team_b_measurements_feed_operational_counts:
        return []
    return get_latest_measurements_by_sensor(session, now=now)


def is_measurement_fresh(
    measurement: TeamBMeasurement,
    *,
    now: datetime | None = None,
) -> bool:
    freshness_minutes = max(
        1,
        get_settings().team_b_measurement_freshness_minutes,
    )
    cutoff = (now or utc_now_naive()) - timedelta(minutes=freshness_minutes)
    return measurement.received_at >= cutoff


def get_measurement_history(
    session: Session,
    limit: int = 100,
) -> list[TeamBMeasurement]:
    statement = (
        select(TeamBMeasurement)
        .order_by(TeamBMeasurement.received_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    return list(session.exec(statement).all())


def prune_team_b_measurements(session: Session, cutoff: datetime) -> int:
    stale_ids = list(
        session.exec(
            select(TeamBMeasurement.id).where(
                TeamBMeasurement.id.is_not(None),
                TeamBMeasurement.received_at < cutoff,
            )
        ).all()
    )
    if not stale_ids:
        return 0

    session.exec(delete(TeamBMeasurement).where(TeamBMeasurement.id.in_(stale_ids)))
    session.commit()
    return len(stale_ids)
