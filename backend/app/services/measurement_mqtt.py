import json
import logging

import paho.mqtt.client as mqtt_client
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.schemas.measurements import MeasurementMessage
from app.services.measurements import store_measurement_from_mqtt
from app.services.thermal_image import thermal_image_store

logger = logging.getLogger(__name__)


def start_measurement_subscriber() -> mqtt_client.Client:
    settings = get_settings()
    client = mqtt_client.Client(
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=f"{settings.mqtt_client_id}-measurements",
    )
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=5, max_delay=60)
    client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()
    return client


def stop_measurement_subscriber(client: mqtt_client.Client | None) -> None:
    if client is None:
        return
    client.loop_stop()
    client.disconnect()


def _on_connect(
    client: mqtt_client.Client,
    userdata: object,
    flags: mqtt_client.ConnectFlags,
    reason_code: mqtt_client.ReasonCode,
    properties: mqtt_client.Properties | None,
) -> None:
    if reason_code == 0:
        settings = get_settings()
        if settings.mqtt_subscribe_measurements:
            client.subscribe(settings.mqtt_measurements_topic)
            logger.info(
                "Subscribed to Team B measurement topic %s",
                settings.mqtt_measurements_topic,
            )
        if settings.mqtt_subscribe_thermal_image:
            client.subscribe(settings.mqtt_thermal_image_topic)
            logger.info(
                "Subscribed to Team B thermal image topic %s",
                settings.mqtt_thermal_image_topic,
            )
    else:
        logger.warning(
            "Could not connect Team B measurement subscriber: %s",
            reason_code,
        )


def _on_message(
    client: mqtt_client.Client,
    userdata: object,
    message: mqtt_client.MQTTMessage,
) -> None:
    settings = get_settings()
    if (
        settings.mqtt_subscribe_thermal_image
        and message.topic == settings.mqtt_thermal_image_topic
    ):
        try:
            frame = thermal_image_store.replace(
                message.payload,
                max_bytes=settings.thermal_image_max_bytes,
            )
            logger.debug(
                "Accepted Team B thermal image on %s: %s bytes, %s",
                message.topic,
                frame.size_bytes,
                frame.media_type,
            )
        except ValueError as exc:
            logger.warning(
                "Ignored invalid Team B thermal image on %s: %s",
                message.topic,
                exc,
            )
        return

    try:
        payload = json.loads(message.payload.decode("utf-8"))
        measurement = MeasurementMessage.model_validate(payload)
        store_measurement_from_mqtt(measurement)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(
            "Ignored malformed Team B measurement payload on %s",
            message.topic,
        )
    except ValidationError as exc:
        logger.warning(
            "Ignored invalid Team B measurement payload on %s: %s",
            message.topic,
            exc,
        )
    except (OSError, SQLAlchemyError) as exc:
        logger.exception(
            "Failed to store Team B measurement from %s: %s",
            message.topic,
            exc,
        )
