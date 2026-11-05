from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import engine
from app.models import SyntheticLocationMeasurement, TeamBMeasurement, TrafficPrediction
from app.schemas.model_status import (
    LatestMeasurementSummary,
    ModelStatusResponse,
    MqttConfigSummary,
    PublishStatusSummary,
)
from app.services.campus_time import campus_naive_to_utc
from app.services.fixedlocations import (
    FIXED_LOCATIONS,
    PHYSICAL_MODEL_LOCATIONS,
    SENSOR_FIXED_LOCATION_MAP,
)
from app.services.measurements import (
    get_latest_measurements_by_sensor,
    get_latest_operational_measurements_by_sensor,
)
from app.services.mqtt import publish_json
from app.services.mqtt_status import get_publish_statuses, record_publish_attempt
from app.services.predictions import get_latest_predictions_by_location
from app.services.synthetic_data import get_latest_synthetic_measurements_by_location

MODEL_STATE_ACTION = "update_model_state"


def build_model_status(session: Session) -> ModelStatusResponse:
    collected_measurements = get_latest_measurements_by_sensor(session)
    operational_measurements = get_latest_operational_measurements_by_sensor(session)
    latest_synthetic = get_latest_synthetic_measurements_by_location(session)
    latest_measurement = max(
        collected_measurements,
        key=lambda measurement: measurement.received_at,
        default=None,
    )
    statuses = list(get_publish_statuses(session).values())
    real_locations = _real_counts_by_location(operational_measurements)
    return ModelStatusResponse(
        data_mode=_data_mode(operational_measurements, latest_synthetic),
        live_sensor_count=len(collected_measurements),
        simulated_location_count=max(0, len(FIXED_LOCATIONS) - len(real_locations)),
        latest_measurement=_latest_measurement_summary(latest_measurement),
        mqtt=_mqtt_config_summary(),
        publish_statuses=[
            PublishStatusSummary.model_validate(status, from_attributes=True)
            for status in statuses
        ],
        last_publish_error=_last_publish_error(statuses),
    )


def publish_model_state_update() -> tuple[dict[str, Any], dict[str, Any], bool]:
    with Session(engine) as session:
        locations_payload = build_locations_payload(session)
        nodes_payload = build_nodes_payload(session)

    if not get_settings().mqtt_publish_model_state:
        return locations_payload, nodes_payload, False

    locations_success = _publish_tracked(
        channel="locations",
        topic=_model_topic("locations"),
        payload=locations_payload,
        payload_source=locations_payload["source"],
    )
    nodes_success = _publish_tracked(
        channel="nodes",
        topic=_model_topic("nodes"),
        payload=nodes_payload,
        payload_source=nodes_payload["source"],
    )
    return locations_payload, nodes_payload, locations_success and nodes_success


def build_locations_payload(session: Session) -> dict[str, Any]:
    latest_measurements = get_latest_operational_measurements_by_sensor(session)
    latest_synthetic = get_latest_synthetic_measurements_by_location(session)
    latest_predictions = get_latest_predictions_by_location(session)
    real_counts = _real_counts_by_location(latest_measurements)
    data_mode = _data_mode(latest_measurements, latest_synthetic)
    return {
        "action": MODEL_STATE_ACTION,
        "type": "locations",
        "source": data_mode,
        "timestamp": _payload_timestamp(latest_measurements, latest_synthetic),
        "payload": [
            _location_state(location, real_counts, latest_synthetic, latest_predictions)
            for location in PHYSICAL_MODEL_LOCATIONS
        ],
    }


def build_nodes_payload(session: Session) -> dict[str, Any]:
    collected_measurements = get_latest_measurements_by_sensor(session)
    operational_measurements = get_latest_operational_measurements_by_sensor(session)
    latest_synthetic = get_latest_synthetic_measurements_by_location(session)
    data_mode = _data_mode(operational_measurements, latest_synthetic)
    live_by_sensor = {
        measurement.sensor_id: measurement for measurement in collected_measurements
    }
    current_total = _current_total(operational_measurements, latest_synthetic)
    return {
        "action": MODEL_STATE_ACTION,
        "type": "nodes",
        "source": data_mode,
        "timestamp": _payload_timestamp(operational_measurements, latest_synthetic),
        "payload": [
            _measurement_node("k1", "light_barrier", live_by_sensor, "k1"),
            _measurement_node("k2", "area", live_by_sensor, "k2"),
            {
                "id": "k3",
                "type": "people_display",
                "status": "active" if current_total > 0 else "waiting",
                "value": current_total,
                "unit": "people",
                "source": data_mode,
                "updated_at": _iso_now(),
            },
            {
                "id": "k4",
                "type": "environment",
                "status": "active",
                "value": "weather",
                "unit": None,
                "source": "weather",
                "updated_at": _iso_now(),
            },
        ],
    }


def _publish_tracked(
    *,
    channel: str,
    topic: str,
    payload: dict[str, Any],
    payload_source: str,
) -> bool:
    try:
        publish_json(topic, payload)
    except OSError as exc:
        record_publish_attempt(
            channel=channel,
            topic=topic,
            success=False,
            error=str(exc),
            payload_source=payload_source,
        )
        return False

    record_publish_attempt(
        channel=channel,
        topic=topic,
        success=True,
        payload_source=payload_source,
    )
    return True


def _location_state(
    location,
    real_counts: dict[str, int],
    latest_synthetic: dict[str, SyntheticLocationMeasurement],
    latest_predictions: dict[str, TrafficPrediction],
) -> dict[str, Any]:
    real_count = real_counts.get(location.id)
    synthetic = latest_synthetic.get(location.id)
    predicted = latest_predictions.get(location.id)
    current_count = (
        real_count
        if real_count is not None
        else synthetic.people_count
        if synthetic
        else 0
    )
    source = "live" if real_count is not None else "simulated"
    timestamp = synthetic.source_timestamp if synthetic is not None else None
    return {
        "id": location.id,
        "name": location.name,
        "current_count": current_count,
        "forecast_count": predicted.weather_adjusted_count
        if predicted
        else current_count,
        "source": source,
        "status": source,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timestamp": int(campus_naive_to_utc(timestamp).replace(tzinfo=UTC).timestamp())
        if timestamp
        else None,
    }


def _measurement_node(
    node_id: str,
    node_type: str,
    live_by_sensor: dict[str, TeamBMeasurement],
    sensor_prefix: str,
) -> dict[str, Any]:
    measurement = next(
        (
            item
            for sensor_id, item in live_by_sensor.items()
            if sensor_id == sensor_prefix or sensor_id.startswith(f"{sensor_prefix}-")
        ),
        None,
    )
    return {
        "id": node_id,
        "type": node_type,
        "status": "live" if measurement is not None else "waiting",
        "value": measurement.people_count if measurement is not None else 0,
        "unit": "people",
        "source": "live" if measurement is not None else "waiting",
        "updated_at": measurement.source_timestamp.isoformat()
        if measurement is not None
        else None,
    }


def _real_counts_by_location(
    measurements: list[TeamBMeasurement],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for measurement in measurements:
        location_id = SENSOR_FIXED_LOCATION_MAP.get(measurement.sensor_id)
        if location_id is not None:
            counts[location_id] = measurement.people_count
    return counts


def _current_total(
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


def _payload_timestamp(
    latest_measurements: list[TeamBMeasurement],
    latest_synthetic: dict[str, SyntheticLocationMeasurement],
) -> int:
    timestamps = [
        int(measurement.source_timestamp.replace(tzinfo=UTC).timestamp())
        for measurement in latest_measurements
    ]
    timestamps.extend(
        int(
            campus_naive_to_utc(measurement.source_timestamp)
            .replace(tzinfo=UTC)
            .timestamp()
        )
        for measurement in latest_synthetic.values()
    )
    return max(timestamps) if timestamps else int(datetime.now(UTC).timestamp())


def _data_mode(
    latest_measurements: list[TeamBMeasurement],
    latest_synthetic: dict[str, SyntheticLocationMeasurement],
) -> str:
    if len(latest_measurements) >= len(FIXED_LOCATIONS):
        return "real"
    if latest_measurements:
        return "mixed"
    if latest_synthetic:
        return "simulated"
    return "simulated"


def _mqtt_config_summary() -> MqttConfigSummary:
    settings = get_settings()
    return MqttConfigSummary(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        topic_prefix=settings.mqtt_topic_prefix,
        measurements_topic=settings.mqtt_measurements_topic,
        thermal_image_topic=settings.mqtt_thermal_image_topic,
        publish_weather=settings.mqtt_publish_weather,
        publish_people_display=settings.mqtt_publish_people_display,
        publish_model_state=settings.mqtt_publish_model_state,
        subscribe_measurements=settings.mqtt_subscribe_measurements,
        subscribe_thermal_image=settings.mqtt_subscribe_thermal_image,
    )


def _latest_measurement_summary(
    measurement: TeamBMeasurement | None,
) -> LatestMeasurementSummary | None:
    if measurement is None:
        return None
    return LatestMeasurementSummary.model_validate(measurement, from_attributes=True)


def _last_publish_error(statuses) -> str | None:
    failed = [
        status for status in statuses if not status.success and status.error is not None
    ]
    if not failed:
        return None
    return max(failed, key=lambda status: status.attempted_at).error


def _model_topic(suffix: str) -> str:
    return f"{get_settings().mqtt_topic_prefix.rstrip('/')}/{suffix}"


def _iso_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()
