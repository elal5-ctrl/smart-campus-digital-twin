from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import SyntheticLocationMeasurement

DayType = str
ModelKey = tuple[str, DayType]
DatasetSignature = tuple[int, datetime | None, str | None]
CacheSignature = tuple[DatasetSignature, int, float, int]


@dataclass(frozen=True)
class FourierModel:
    coefficients: np.ndarray
    count_cap: float


_cached_signature: CacheSignature | None = None
_cached_models: dict[ModelKey, FourierModel] = {}


def get_fourier_models(session: Session) -> dict[ModelKey, FourierModel]:
    global _cached_models, _cached_signature

    settings = get_settings()
    signature = (
        synthetic_dataset_signature(session),
        settings.predictions_fourier_harmonics,
        settings.predictions_fourier_ridge_alpha,
        settings.predictions_fourier_minimum_samples,
    )
    if signature == _cached_signature:
        return _cached_models

    models = fit_fourier_models(
        session,
        harmonics=settings.predictions_fourier_harmonics,
        ridge_alpha=settings.predictions_fourier_ridge_alpha,
        minimum_samples=settings.predictions_fourier_minimum_samples,
    )
    _cached_signature = signature
    _cached_models = models
    return models


def synthetic_dataset_signature(session: Session) -> DatasetSignature:
    count, latest_created_at, generation_version = session.exec(
        select(
            func.count(SyntheticLocationMeasurement.id),
            func.max(SyntheticLocationMeasurement.created_at),
            func.max(SyntheticLocationMeasurement.generation_version),
        )
    ).one()
    return int(count or 0), latest_created_at, generation_version


def fit_fourier_models(
    session: Session,
    *,
    harmonics: int,
    ridge_alpha: float,
    minimum_samples: int,
) -> dict[ModelKey, FourierModel]:
    rows = session.exec(
        select(
            SyntheticLocationMeasurement.location_id,
            SyntheticLocationMeasurement.source_timestamp,
            SyntheticLocationMeasurement.people_count,
        ).order_by(
            SyntheticLocationMeasurement.location_id,
            SyntheticLocationMeasurement.source_timestamp,
        )
    ).all()

    samples: dict[ModelKey, list[tuple[float, float]]] = {}
    for location_id, timestamp, people_count in rows:
        day_type = _day_type(timestamp)
        samples.setdefault((location_id, day_type), []).append(
            (_fractional_hour(timestamp), float(people_count))
        )

    return {
        key: model
        for key, values in samples.items()
        if (
            model := fit_fourier_model(
                values,
                harmonics=harmonics,
                ridge_alpha=ridge_alpha,
                minimum_samples=minimum_samples,
            )
        )
        is not None
    }


def fit_fourier_model(
    samples: list[tuple[float, float]],
    *,
    harmonics: int,
    ridge_alpha: float,
    minimum_samples: int,
) -> FourierModel | None:
    if len(samples) < minimum_samples:
        return None

    hours = np.asarray([hour for hour, _ in samples], dtype=float)
    counts = np.asarray([count for _, count in samples], dtype=float)
    design = build_fourier_features(hours, harmonics)
    regularization = np.eye(design.shape[1], dtype=float) * max(0.0, ridge_alpha)
    regularization[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + regularization,
        design.T @ counts,
    )
    return FourierModel(
        coefficients=coefficients,
        count_cap=max(0.0, float(np.percentile(counts, 99))),
    )


def predict_fourier_count(
    models: dict[ModelKey, FourierModel],
    *,
    location_id: str,
    timestamp: datetime,
    harmonics: int,
) -> int | None:
    day_type = _day_type(timestamp)
    model = models.get((location_id, day_type))
    if model is None:
        model = models.get((location_id, "weekday"))
    if model is None:
        return None

    features = build_fourier_features(
        np.asarray([_fractional_hour(timestamp)], dtype=float),
        harmonics,
    )
    prediction = float(features[0] @ model.coefficients)
    return max(0, int(round(min(prediction, model.count_cap))))


def build_fourier_features(hours: np.ndarray, harmonics: int) -> np.ndarray:
    columns = [np.ones(len(hours), dtype=float)]
    for harmonic in range(1, harmonics + 1):
        angle = 2 * np.pi * harmonic * hours / 24.0
        columns.extend((np.sin(angle), np.cos(angle)))
    return np.column_stack(columns)


def clear_fourier_cache() -> None:
    global _cached_models, _cached_signature
    _cached_signature = None
    _cached_models = {}


def _fractional_hour(timestamp: datetime) -> float:
    return timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600


def _day_type(timestamp: datetime) -> DayType:
    return "weekend" if timestamp.weekday() >= 5 else "weekday"
