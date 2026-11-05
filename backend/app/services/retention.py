from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import SyntheticLocationMeasurement, TeamBMeasurement, TrafficPrediction
from app.services.weather import prune_weather_readings


def run_retention_cleanup() -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        deleted = {
            "team_b_measurements": _delete_older_than(
                session,
                TeamBMeasurement,
                TeamBMeasurement.received_at,
                now - timedelta(days=settings.team_b_measurement_retention_days),
            ),
            "traffic_predictions": _delete_older_than(
                session,
                TrafficPrediction,
                TrafficPrediction.target_timestamp,
                now - timedelta(days=settings.predictions_retention_days),
            ),
            "synthetic_location_measurements": _delete_older_than(
                session,
                SyntheticLocationMeasurement,
                SyntheticLocationMeasurement.source_timestamp,
                now - timedelta(days=settings.synthetic_retention_days),
            ),
            "weather_readings": prune_weather_readings(
                session,
                settings.weather_retention_rows,
            ),
        }
        session.commit()
        return deleted


def _delete_older_than(session: Session, model: type, column, cutoff: datetime) -> int:
    ids = list(
        session.exec(
            select(model.id).where(model.id.is_not(None), column < cutoff)
        ).all()
    )
    if not ids:
        return 0
    session.exec(delete(model).where(model.id.in_(ids)))
    return len(ids)
