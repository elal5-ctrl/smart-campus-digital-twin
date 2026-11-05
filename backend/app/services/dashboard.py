from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Entry, SyntheticLocationMeasurement, TeamBMeasurement
from app.services.campus_time import utc_naive_to_campus
from app.services.fixedlocations import (
    EXTERNAL_SENSOR_LOCATION_IDS,
    FIXED_LOCATIONS,
    FIXED_LOCATIONS_BY_ID,
    SENSOR_FIXED_LOCATION_MAP,
    FixedLocationDefinition,
)
from app.services.measurements import get_latest_operational_measurements_by_sensor
from app.services.predictions import (
    get_latest_predictions_by_location,
    get_prediction_totals,
)
from app.services.synthetic_data import (
    current_campus_interval,
    get_latest_synthetic_measurements_by_location,
)

LocalizedText = dict[str, str]
KnownMapPosition = tuple[float, float]

TEAM_B_SENSOR_POSITIONS: dict[str, KnownMapPosition] = {
    "k1-light-barrier-01": (34.8089451, 135.5598084),
    "k2-area-01": (34.8099864, 135.5620731),
}
TEAM_B_ZONE_POSITIONS: dict[str, KnownMapPosition] = {
    "k1": (34.8089451, 135.5598084),
    "k2": (34.8099864, 135.5620731),
}


def build_dashboard_data(session: Session) -> dict[str, Any]:
    fixed_location_data = _build_fixed_location_dashboard_data(session)
    if fixed_location_data["sensorPoints"]:
        return fixed_location_data

    latest_timestamp = session.exec(select(func.max(Entry.timestamp))).one()

    if latest_timestamp is None:
        return {
            "latestTimestamp": None,
            "sensorPoints": [],
            "heatmapPoints": [],
            "recommendations": [],
            "measuredHours": [],
            "forecastHours": [],
        }

    latest_entries = _get_entries_at_timestamp(session, latest_timestamp)
    hourly_totals = _get_hourly_totals(session)

    return {
        "latestTimestamp": latest_timestamp.isoformat(),
        "sensorPoints": _build_sensor_points(latest_entries),
        "heatmapPoints": _build_heatmap_points(_build_sensor_points(latest_entries)),
        "recommendations": _build_recommendations(latest_entries),
        "measuredHours": [total for _, total in hourly_totals],
        "forecastHours": [],
    }


def _build_fixed_location_dashboard_data(session: Session) -> dict[str, Any]:
    latest_measurements = get_latest_operational_measurements_by_sensor(session)
    latest_synthetic = get_latest_synthetic_measurements_by_location(session)
    latest_predictions = get_latest_predictions_by_location(session)
    real_counts = _real_counts_by_location(latest_measurements)
    sensor_points = [
        _build_fixed_location_sensor_point(
            location=location,
            real_count=real_counts.get(location.id),
            synthetic_measurement=latest_synthetic.get(location.id),
            forecast=latest_predictions.get(location.id).weather_adjusted_count
            if location.id in latest_predictions
            else None,
        )
        for location in FIXED_LOCATIONS
    ]

    timestamps = [
        utc_naive_to_campus(measurement.source_timestamp).replace(tzinfo=None)
        for measurement in latest_measurements
    ] + [measurement.source_timestamp for measurement in latest_synthetic.values()]
    latest_timestamp = max(timestamps).isoformat() if timestamps else None

    return {
        "latestTimestamp": latest_timestamp,
        "sensorPoints": sensor_points,
        "heatmapPoints": _build_heatmap_points(sensor_points),
        "recommendations": _build_fixed_location_recommendations(sensor_points),
        "measuredHours": _get_fixed_location_measured_hours(session),
        "forecastHours": get_prediction_totals(session),
    }


def _build_fixed_location_sensor_point(
    *,
    location: FixedLocationDefinition,
    real_count: int | None,
    synthetic_measurement: SyntheticLocationMeasurement | None,
    forecast: int | None,
) -> dict[str, Any]:
    measured = (
        real_count
        if real_count is not None
        else synthetic_measurement.people_count
        if synthetic_measurement is not None
        else 0
    )
    status = _fixed_location_status(location, real_count)
    return {
        "id": location.id,
        "name": _fixed_location_name(location),
        "kind": "zone",
        "measured": measured,
        "forecast": forecast if forecast is not None else measured,
        "confidence": 100 if status == "live" else 0,
        "position": _fixed_location_map_position(location),
        "status": status,
    }


def _fixed_location_status(
    location: FixedLocationDefinition,
    real_count: int | None,
) -> str:
    if real_count is not None:
        return "live"
    if location.id in EXTERNAL_SENSOR_LOCATION_IDS:
        return "waiting"
    return "live"


def _real_counts_by_location(
    measurements: list[TeamBMeasurement],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for measurement in measurements:
        location_id = SENSOR_FIXED_LOCATION_MAP.get(measurement.sensor_id)
        if location_id in FIXED_LOCATIONS_BY_ID:
            counts[location_id] = measurement.people_count
    return counts


def _fixed_location_name(location: FixedLocationDefinition) -> LocalizedText:
    return {
        "de": location.name,
        "en": location.name,
        "ja": location.name,
    }


def _fixed_location_map_position(location: FixedLocationDefinition) -> KnownMapPosition:
    return (location.latitude, location.longitude)


def _get_fixed_location_measured_hours(session: Session) -> list[int]:
    statement = (
        select(
            SyntheticLocationMeasurement.source_timestamp,
            func.sum(SyntheticLocationMeasurement.people_count).label("count"),
        )
        .where(
            SyntheticLocationMeasurement.source_timestamp <= current_campus_interval()
        )
        .group_by(SyntheticLocationMeasurement.source_timestamp)
        .order_by(SyntheticLocationMeasurement.source_timestamp)
    )
    totals = [int(total or 0) for _, total in session.exec(statement)]
    if totals:
        return totals[-24:]
    return _get_team_b_hourly_totals(session)


def _build_fixed_location_recommendations(
    sensor_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not sensor_points:
        return []

    busiest = max(sensor_points, key=lambda point: point["measured"])
    if busiest["measured"] < 20:
        return [
            {
                "place": busiest["name"],
                "reason": {
                    "de": (
                        f"Ruhige Lage: Der höchste Standort liegt bei "
                        f"{busiest['measured']} Personen. Weiter beobachten, "
                        "aktuell ist keine Besucherlenkung nötig."
                    ),
                    "en": (
                        f"Calm conditions: the highest location is at "
                        f"{busiest['measured']} people. Keep monitoring; no "
                        "visitor routing is needed right now."
                    ),
                    "ja": (
                        f"落ち着いた状況です。最大地点は{busiest['measured']}人です。"
                        "現在、人の流れを誘導する必要はありません。"
                    ),
                },
                "priority": "niedrig",
            }
        ]

    return [
        {
            "place": busiest["name"],
            "reason": {
                "de": (
                    f"Höchste aktuelle Auslastung mit {busiest['measured']} "
                    "Personen. Prüfen Sie diesen Bereich zuerst, wenn Besucherströme "
                    "gelenkt werden müssen."
                ),
                "en": (
                    f"Highest current load with {busiest['measured']} people. "
                    "Check this area first when visitor flow needs attention."
                ),
                "ja": (
                    f"現在の最大負荷は{busiest['measured']}人です。"
                    "人の流れを調整する場合は、このエリアを先に確認してください。"
                ),
            },
            "priority": _priority_for_count(busiest["measured"]),
        }
    ]


def _build_team_b_dashboard_data(
    session: Session,
    latest_measurements: list[TeamBMeasurement],
) -> dict[str, Any]:
    latest_timestamp = max(
        measurement.source_timestamp for measurement in latest_measurements
    )

    return {
        "latestTimestamp": latest_timestamp.isoformat(),
        "sensorPoints": _build_team_b_sensor_points(latest_measurements),
        "heatmapPoints": _build_heatmap_points(
            _build_team_b_sensor_points(latest_measurements)
        ),
        "recommendations": _build_team_b_recommendations(latest_measurements),
        "measuredHours": _get_team_b_hourly_totals(session),
        "forecastHours": [],
    }


def _build_heatmap_points(sensor_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_expected_count = max(
        1,
        *(max(point["measured"], point["forecast"]) for point in sensor_points),
    )
    return [
        {
            "id": point["id"],
            "position": point["position"],
            "intensity": round(
                min(
                    max(point["measured"], point["forecast"]) / max_expected_count,
                    1,
                ),
                3,
            ),
            "measured": point["measured"],
            "forecast": point["forecast"],
            "source": "live" if point["status"] == "live" else "synthetic",
        }
        for point in sensor_points
    ]


def _build_team_b_sensor_points(
    measurements: list[TeamBMeasurement],
) -> list[dict[str, Any]]:
    return [
        {
            "id": measurement.sensor_id,
            "name": _team_b_sensor_name(measurement),
            "kind": _sensor_kind_for_type(measurement.sensor_type),
            "measured": measurement.people_count,
            "forecast": measurement.people_count,
            "confidence": 100,
            "position": _team_b_map_position(measurement),
            "status": "live",
        }
        for measurement in sorted(
            measurements,
            key=lambda item: (item.floor_level, item.zone_id, item.sensor_id),
        )
    ]


def _team_b_sensor_name(measurement: TeamBMeasurement) -> LocalizedText:
    label = measurement.sensor_id.replace("-", " ").title()
    return {
        "de": f"{label} · Ebene {measurement.floor_level}",
        "en": f"{label} · Floor {measurement.floor_level}",
        "ja": f"{label} · {measurement.floor_level}階",
    }


def _sensor_kind_for_type(sensor_type: str) -> str:
    if sensor_type == "light_barrier":
        return "entry"
    if sensor_type == "area":
        return "zone"
    return "zone"


def _team_b_map_position(measurement: TeamBMeasurement) -> KnownMapPosition:
    return (
        TEAM_B_SENSOR_POSITIONS.get(measurement.sensor_id)
        or TEAM_B_ZONE_POSITIONS.get(measurement.zone_id)
        or (50, 50)
    )


def _get_team_b_hourly_totals(session: Session) -> list[int]:
    statement = (
        select(
            TeamBMeasurement.source_timestamp,
            func.sum(TeamBMeasurement.people_count).label("people_count"),
        )
        .group_by(TeamBMeasurement.source_timestamp)
        .order_by(TeamBMeasurement.source_timestamp)
    )

    return [int(total or 0) for _, total in session.exec(statement)]


def _get_entries_at_timestamp(
    session: Session,
    timestamp: datetime,
) -> list[tuple[int, int, int, float, float]]:
    statement = (
        select(
            Entry.id,
            Entry.total_count,
            Entry.level,
            func.ST_Y(Entry.coordinates).label("latitude"),
            func.ST_X(Entry.coordinates).label("longitude"),
        )
        .where(Entry.timestamp == timestamp)
        .order_by(Entry.level, Entry.id)
    )

    return list(session.exec(statement).all())


def _get_hourly_totals(session: Session) -> list[tuple[datetime, int]]:
    statement = (
        select(
            Entry.timestamp,
            func.sum(Entry.total_count).label("total_count"),
        )
        .group_by(Entry.timestamp)
        .order_by(Entry.timestamp)
    )

    return [
        (timestamp, int(total_count or 0))
        for timestamp, total_count in session.exec(statement)
    ]


def _build_sensor_points(
    entries: list[tuple[int, int, int, float, float]],
) -> list[dict[str, Any]]:
    if not entries:
        return []

    latitudes = [latitude for _, _, _, latitude, _ in entries]
    longitudes = [longitude for _, _, _, _, longitude in entries]
    min_latitude = min(latitudes)
    max_latitude = max(latitudes)
    min_longitude = min(longitudes)
    max_longitude = max(longitudes)

    return [
        {
            "id": f"F{level}-{index:02d}",
            "name": _sensor_name(index=index, level=level),
            "kind": "zone",
            "measured": int(total_count),
            "forecast": int(total_count),
            "confidence": 100,
            "position": _map_position(
                latitude=latitude,
                longitude=longitude,
                min_latitude=min_latitude,
                max_latitude=max_latitude,
                min_longitude=min_longitude,
                max_longitude=max_longitude,
            ),
            "status": "live",
        }
        for index, (_, total_count, level, latitude, longitude) in enumerate(
            entries, start=1
        )
    ]


def _sensor_name(index: int, level: int) -> LocalizedText:
    return {
        "de": f"Messpunkt {index} · Ebene {level}",
        "en": f"Measurement point {index} · Floor {level}",
        "ja": f"測定点 {index} · {level}階",
    }


def _map_position(
    *,
    latitude: float,
    longitude: float,
    min_latitude: float,
    max_latitude: float,
    min_longitude: float,
    max_longitude: float,
) -> list[float]:
    y = _scale_to_map(latitude, min_latitude, max_latitude, 14, 82)
    x = _scale_to_map(longitude, min_longitude, max_longitude, 14, 86)
    return [round(y, 2), round(x, 2)]


def _scale_to_map(
    value: float,
    minimum: float,
    maximum: float,
    target_minimum: float,
    target_maximum: float,
) -> float:
    if minimum == maximum:
        return (target_minimum + target_maximum) / 2

    ratio = (value - minimum) / (maximum - minimum)
    return target_minimum + ratio * (target_maximum - target_minimum)


def _build_recommendations(
    entries: list[tuple[int, int, int, float, float]],
) -> list[dict[str, Any]]:
    if not entries:
        return []

    busiest = max(entries, key=lambda entry: entry[1])
    _, total_count, level, _, _ = busiest

    recommendations = [
        {
            "place": _sensor_name(index=entries.index(busiest) + 1, level=level),
            "reason": {
                "de": (
                    f"Höchste aktuelle Auslastung mit {total_count} Personen. "
                    "Dieser Bereich sollte bei der aktuellen Lage zuerst "
                    "geprüft werden."
                ),
                "en": (
                    f"Highest current load with {total_count} people. "
                    "This area should be checked first under the current conditions."
                ),
                "ja": (
                    f"現在の最大負荷は{total_count}人です。"
                    "現在の状況では、このエリアを先に確認してください。"
                ),
            },
            "priority": _priority_for_count(total_count),
        }
    ]

    zero_count_entries = [entry for entry in entries if entry[1] == 0]
    if zero_count_entries:
        recommendations.append(
            {
                "place": {"de": "Nullwerte", "en": "Zero counts", "ja": "ゼロ値"},
                "reason": {
                    "de": (
                        f"{len(zero_count_entries)} Messpunkt(e) melden 0 Personen. "
                        "Diese Werte sollten vor der Analyse geprüft werden."
                    ),
                    "en": (
                        f"{len(zero_count_entries)} measurement point(s) report "
                        "0 people. "
                        "Check these values before analysis."
                    ),
                    "ja": (
                        f"{len(zero_count_entries)}個の測定点が0人を報告しています。"
                        "分析前に確認してください。"
                    ),
                },
                "priority": "mittel",
            }
        )

    return recommendations


def _build_team_b_recommendations(
    measurements: list[TeamBMeasurement],
) -> list[dict[str, Any]]:
    if not measurements:
        return []

    busiest = max(measurements, key=lambda measurement: measurement.people_count)
    recommendations = [
        {
            "place": _team_b_sensor_name(busiest),
            "reason": {
                "de": (
                    f"Höchste aktuelle Auslastung mit {busiest.people_count} "
                    "Personen aus Team-B-Messdaten."
                ),
                "en": (
                    f"Highest current load with {busiest.people_count} people "
                    "from Team B measurements."
                ),
                "ja": (
                    f"Team Bの測定では現在の最大負荷は{busiest.people_count}人です。"
                ),
            },
            "priority": _priority_for_count(busiest.people_count),
        }
    ]

    zero_count_measurements = [
        measurement for measurement in measurements if measurement.people_count == 0
    ]
    if zero_count_measurements:
        recommendations.append(
            {
                "place": {"de": "Nullwerte", "en": "Zero counts", "ja": "ゼロ値"},
                "reason": {
                    "de": (
                        f"{len(zero_count_measurements)} Team-B-Sensor(en) melden "
                        "0 Personen. Diese Werte sollten vor der Analyse geprüft "
                        "werden."
                    ),
                    "en": (
                        f"{len(zero_count_measurements)} Team B sensor(s) report "
                        "0 people. Check these values before analysis."
                    ),
                    "ja": (
                        f"{len(zero_count_measurements)}個のTeam Bセンサーが"
                        "0人を報告しています。分析前に確認してください。"
                    ),
                },
                "priority": "mittel",
            }
        )

    return recommendations


def _priority_for_count(total_count: int) -> str:
    if total_count >= 85:
        return "hoch"
    if total_count >= 55:
        return "mittel"
    return "niedrig"
