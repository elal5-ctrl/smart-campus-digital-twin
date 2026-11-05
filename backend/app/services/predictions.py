from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, func
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import (
    SyntheticLocationMeasurement,
    TeamBMeasurement,
    TrafficPrediction,
    WeatherReading,
)
from app.services.campus_time import utc_naive_to_campus, utc_now_naive
from app.services.fixedlocations import (
    FIXED_LOCATIONS,
    FIXED_LOCATIONS_BY_ID,
    SENSOR_FIXED_LOCATION_MAP,
)
from app.services.fourier_forecasting import (
    get_fourier_models,
    predict_fourier_count,
)
from app.services.measurements import get_latest_operational_measurements_by_sensor
from app.services.synthetic_data import (
    SYNTHETIC_INTERVAL_MINUTES,
    get_latest_synthetic_measurements_by_location,
    refresh_synthetic_location_measurements,
)

PREDICTION_INTERVAL_MINUTES = 15


def create_predictions_table() -> None:
    TrafficPrediction.__table__.create(engine, checkfirst=True)


def refresh_traffic_predictions() -> int:
    settings = get_settings()
    if not settings.predictions_enabled:
        return 0

    if settings.synthetic_generation_enabled:
        refresh_synthetic_location_measurements()

    with Session(engine) as session:
        rows = build_prediction_rows(session)
        for row in rows:
            existing = session.exec(
                select(TrafficPrediction).where(
                    TrafficPrediction.location_id == row.location_id,
                    TrafficPrediction.target_timestamp == row.target_timestamp,
                    TrafficPrediction.model_version == row.model_version,
                )
            ).first()
            if existing is None:
                session.add(row)
            else:
                _update_prediction(existing, row)
                session.add(existing)

        session.commit()
        prune_traffic_predictions(session, settings.predictions_retention_rows)
        return len(rows)


def build_prediction_rows(session: Session) -> list[TrafficPrediction]:
    settings = get_settings()
    generated_at = utc_now_naive()
    weather = _latest_weather(session)
    weather_condition = weather.condition if weather is not None else None
    weather_factor = _weather_multiplier(weather_condition)
    live_location_counts = _latest_real_counts_by_location(session)
    current_synthetic = get_latest_synthetic_measurements_by_location(session)
    synthetic_profile = _synthetic_profile_by_location_and_slot(session)
    fourier_models = get_fourier_models(session)

    rows: list[TrafficPrediction] = []
    for timestamp in _future_timestamps(
        generated_at, settings.predictions_horizon_hours
    ):
        campus_timestamp = utc_naive_to_campus(timestamp)
        day_type = "weekend" if campus_timestamp.weekday() >= 5 else "weekday"
        for location in FIXED_LOCATIONS:
            synthetic_count = _synthetic_count_for_location(
                synthetic_profile=synthetic_profile,
                location_id=location.id,
                day_type=day_type,
                slot=_quarter_hour_slot(campus_timestamp),
                fallback_count=current_synthetic.get(location.id).people_count
                if location.id in current_synthetic
                else 0,
            )
            fourier_count = predict_fourier_count(
                fourier_models,
                location_id=location.id,
                timestamp=campus_timestamp,
                harmonics=settings.predictions_fourier_harmonics,
            )
            base_count = fourier_count if fourier_count is not None else synthetic_count
            predicted_count = _blend_live_count(
                base_count,
                live_location_counts.get(location.id),
            )
            weather_adjusted_count = max(
                0,
                int(round(predicted_count * weather_factor)),
            )
            rows.append(
                TrafficPrediction(
                    generated_at=generated_at,
                    target_timestamp=timestamp,
                    location_id=location.id,
                    location_name=location.name,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    base_count=base_count,
                    predicted_count=predicted_count,
                    weather_adjusted_count=weather_adjusted_count,
                    weather_condition=weather_condition,
                    weather_multiplier=weather_factor,
                    model_version=settings.predictions_model_version,
                )
            )

    return rows


def get_latest_predictions_by_location(
    session: Session,
) -> dict[str, TrafficPrediction]:
    target = utc_now_naive() + timedelta(hours=1)
    return _predictions_nearest_target(_latest_prediction_batch(session), target)


def _predictions_nearest_target(
    rows: list[TrafficPrediction],
    target: datetime,
) -> dict[str, TrafficPrediction]:
    predictions: dict[str, TrafficPrediction] = {}
    distances: dict[str, float] = {}
    for prediction in rows:
        distance = abs((prediction.target_timestamp - target).total_seconds())
        if (
            prediction.location_id not in predictions
            or distance < distances[prediction.location_id]
        ):
            predictions[prediction.location_id] = prediction
            distances[prediction.location_id] = distance
    return predictions


def get_prediction_history(
    session: Session,
    limit: int = 100,
) -> list[TrafficPrediction]:
    statement = (
        select(TrafficPrediction)
        .order_by(
            TrafficPrediction.target_timestamp.desc(),
            TrafficPrediction.location_id,
        )
        .limit(max(1, min(limit, 500)))
    )
    return list(session.exec(statement).all())


def get_prediction_totals(session: Session) -> list[int]:
    totals: dict[datetime, int] = defaultdict(int)
    for prediction in _latest_prediction_batch(session):
        totals[prediction.target_timestamp] += prediction.weather_adjusted_count
    return [totals[timestamp] for timestamp in sorted(totals)]


def get_one_hour_prediction_total(session: Session) -> int | None:
    predictions = get_latest_predictions_by_location(session)
    if not predictions:
        return None
    return sum(item.weather_adjusted_count for item in predictions.values())


def prune_traffic_predictions(session: Session, max_rows: int) -> int:
    if max_rows <= 0:
        return 0

    stale_ids = list(
        session.exec(
            select(TrafficPrediction.id)
            .where(TrafficPrediction.id.is_not(None))
            .order_by(
                TrafficPrediction.target_timestamp.desc(),
                TrafficPrediction.generated_at.desc(),
                TrafficPrediction.id.desc(),
            )
            .offset(max_rows)
        ).all()
    )
    if not stale_ids:
        return 0

    session.exec(delete(TrafficPrediction).where(TrafficPrediction.id.in_(stale_ids)))
    session.commit()
    return len(stale_ids)


def _latest_real_counts_by_location(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for measurement in get_latest_operational_measurements_by_sensor(session):
        location_id = SENSOR_FIXED_LOCATION_MAP.get(measurement.sensor_id)
        if location_id is not None:
            counts[location_id] = measurement.people_count
    return counts


def _synthetic_profile_by_location_and_slot(
    session: Session,
) -> dict[tuple[str, str, int], int]:
    statement = (
        select(
            SyntheticLocationMeasurement.location_id,
            SyntheticLocationMeasurement.source_timestamp,
            func.avg(SyntheticLocationMeasurement.people_count).label("count"),
        )
        .group_by(
            SyntheticLocationMeasurement.location_id,
            SyntheticLocationMeasurement.source_timestamp,
        )
        .order_by(SyntheticLocationMeasurement.location_id)
    )

    buckets: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for location_id, source_timestamp, avg_count in session.exec(statement):
        day_type = "weekend" if source_timestamp.weekday() >= 5 else "weekday"
        buckets[(location_id, day_type, _quarter_hour_slot(source_timestamp))].append(
            int(round(float(avg_count or 0)))
        )

    return {
        key: max(0, int(round(sum(values) / len(values))))
        for key, values in buckets.items()
        if values
    }


def _synthetic_count_for_location(
    *,
    synthetic_profile: dict[tuple[str, str, int], int],
    location_id: str,
    day_type: str,
    slot: int,
    fallback_count: int,
) -> int:
    synthetic_count = synthetic_profile.get(
        (location_id, day_type, slot),
        synthetic_profile.get((location_id, "weekday", slot), fallback_count),
    )
    return max(0, synthetic_count)


def _blend_live_count(base_count: int, live_count: int | None) -> int:
    if live_count is None:
        return base_count
    return max(0, int(round((live_count + base_count) / 2)))


def _quarter_hour_slot(timestamp: datetime) -> int:
    return (timestamp.hour * 60 + timestamp.minute) // SYNTHETIC_INTERVAL_MINUTES


def _future_timestamps(now: datetime, horizon_hours: int) -> list[datetime]:
    start = _ceil_to_interval(now, PREDICTION_INTERVAL_MINUTES)
    steps = max(1, horizon_hours * 60 // PREDICTION_INTERVAL_MINUTES)
    return [
        start + timedelta(minutes=PREDICTION_INTERVAL_MINUTES * offset)
        for offset in range(steps)
    ]


def _ceil_to_interval(value: datetime, interval_minutes: int) -> datetime:
    base = value.replace(second=0, microsecond=0)
    minute_remainder = base.minute % interval_minutes
    if minute_remainder == 0:
        return base
    return base + timedelta(minutes=interval_minutes - minute_remainder)


def _latest_prediction_batch(session: Session) -> list[TrafficPrediction]:
    latest_generated_at = session.exec(
        select(func.max(TrafficPrediction.generated_at))
    ).one()
    if latest_generated_at is None:
        return []
    return list(
        session.exec(
            select(TrafficPrediction)
            .where(TrafficPrediction.generated_at == latest_generated_at)
            .order_by(
                TrafficPrediction.target_timestamp,
                TrafficPrediction.location_id,
            )
        ).all()
    )


def _latest_weather(session: Session) -> WeatherReading | None:
    return session.exec(
        select(WeatherReading).order_by(WeatherReading.source_timestamp.desc())
    ).first()


def _weather_multiplier(condition: str | None) -> float:
    settings = get_settings()
    if condition == "sunny":
        return 1.0 + settings.predictions_sunny_boost
    if condition in {"rain", "drizzle", "thunderstorm"}:
        return max(0.0, 1.0 - settings.predictions_rainy_penalty)
    return 1.0


def _update_prediction(target: TrafficPrediction, source: TrafficPrediction) -> None:
    target.generated_at = source.generated_at
    target.location_name = source.location_name
    target.latitude = source.latitude
    target.longitude = source.longitude
    target.base_count = source.base_count
    target.predicted_count = source.predicted_count
    target.weather_adjusted_count = source.weather_adjusted_count
    target.weather_condition = source.weather_condition
    target.weather_multiplier = source.weather_multiplier


def fixed_location_for_sensor(measurement: TeamBMeasurement) -> str | None:
    location_id = SENSOR_FIXED_LOCATION_MAP.get(measurement.sensor_id)
    if location_id not in FIXED_LOCATIONS_BY_ID:
        return None
    return location_id
