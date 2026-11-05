import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import paho.mqtt.client as mqtt_client
import paho.mqtt.publish as mqtt_publish

from app.core.config import get_settings
from app.models import WeatherReading


def publish_weather_reading(reading: WeatherReading) -> None:
    publish_json(weather_topic(), _weather_payload(reading))


def publish_people_display(payload: dict[str, Any]) -> None:
    publish_json(people_display_topic(), payload)


def weather_topic() -> str:
    settings = get_settings()
    return f"{settings.mqtt_topic_prefix.rstrip('/')}/weather"


def people_display_topic() -> str:
    settings = get_settings()
    return f"{settings.mqtt_topic_prefix.rstrip('/')}/people-display"


def publish_json(topic: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    payload_json = json.dumps(payload, separators=(",", ":"))
    mqtt_publish.single(
        topic,
        payload=payload_json,
        qos=0,
        retain=False,
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id=settings.mqtt_client_id,
        keepalive=60,
        protocol=mqtt_client.MQTTv311,
    )


def _weather_payload(reading: WeatherReading) -> dict[str, Any]:
    return {
        "action": "update_weather",
        "payload": {
            "condition": reading.condition,
            "current_temp": reading.temperature_c,
            "temp_high": reading.temp_high_c,
            "temp_low": reading.temp_low_c,
            "rain_chance_pct": reading.rain_chance_pct,
        },
        "timestamp": unix_timestamp(reading.source_timestamp, reading.timezone),
    }


def unix_timestamp(value: datetime, timezone_name: str) -> int:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")

    return int(value.replace(tzinfo=timezone).timestamp())
