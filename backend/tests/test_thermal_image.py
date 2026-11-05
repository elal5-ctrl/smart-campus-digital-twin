import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import thermal_image as thermal_image_router
from app.services import measurement_mqtt, thermal_image

JPEG = b"\xff\xd8\xff\xe0jpeg-data"
PNG = b"\x89PNG\r\n\x1a\npng-data"


def _settings(**overrides):
    values = {
        "mqtt_subscribe_measurements": True,
        "mqtt_subscribe_thermal_image": True,
        "mqtt_measurements_topic": "team-b/thermal/people_count",
        "mqtt_thermal_image_topic": "team-b/thermal/image/web",
        "thermal_image_max_bytes": 1024,
        "thermal_image_freshness_seconds": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ThermalImageStoreTests(TestCase):
    def setUp(self):
        thermal_image.thermal_image_store.clear()

    def tearDown(self):
        thermal_image.thermal_image_store.clear()

    def test_detects_jpeg_and_png_signatures(self):
        self.assertEqual(thermal_image.detect_image_media_type(JPEG), "image/jpeg")
        self.assertEqual(thermal_image.detect_image_media_type(PNG), "image/png")

    def test_rejects_empty_unknown_and_oversized_payloads(self):
        store = thermal_image.ThermalImageStore()
        for payload, max_bytes in ((b"", 100), (b"not-an-image", 100), (JPEG, 4)):
            with self.subTest(payload=payload, max_bytes=max_bytes):
                with self.assertRaises(ValueError):
                    store.replace(payload, max_bytes=max_bytes)

    def test_replacement_changes_revision_and_keeps_latest_frame(self):
        store = thermal_image.ThermalImageStore()
        first = store.replace(
            JPEG,
            max_bytes=1024,
            received_at=datetime(2026, 6, 24, 8, 0, 0),
        )
        second = store.replace(
            PNG,
            max_bytes=1024,
            received_at=datetime(2026, 6, 24, 8, 0, 1),
        )

        self.assertNotEqual(first.revision, second.revision)
        self.assertEqual(store.get(), second)

    def test_concurrent_replacements_remain_consistent(self):
        store = thermal_image.ThermalImageStore()
        payloads = [JPEG + bytes([index]) for index in range(32)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            frames = list(
                executor.map(
                    lambda payload: store.replace(payload, max_bytes=1024),
                    payloads,
                )
            )

        current = store.get()
        self.assertIsNotNone(current)
        self.assertIn(current, frames)
        self.assertEqual(current.size_bytes, len(current.data))

    def test_status_reports_waiting_live_and_stale(self):
        settings = _settings()
        now = datetime(2026, 6, 24, 8, 0, 30)
        with patch.object(thermal_image, "get_settings", return_value=settings):
            waiting = thermal_image.build_thermal_image_status(now=now)
            self.assertEqual(waiting.state, "waiting")
            self.assertFalse(waiting.available)

            thermal_image.thermal_image_store.replace(
                JPEG,
                max_bytes=1024,
                received_at=now - timedelta(seconds=10),
            )
            self.assertEqual(
                thermal_image.build_thermal_image_status(now=now).state,
                "live",
            )
            self.assertEqual(
                thermal_image.build_thermal_image_status(
                    now=now + timedelta(seconds=10)
                ).state,
                "stale",
            )


class ThermalImageMqttTests(TestCase):
    def setUp(self):
        thermal_image.thermal_image_store.clear()

    def tearDown(self):
        thermal_image.thermal_image_store.clear()

    def test_image_payload_bypasses_json_measurement_ingest(self):
        message = SimpleNamespace(
            topic="team-b/thermal/image/web",
            payload=JPEG,
        )
        with (
            patch.object(measurement_mqtt, "get_settings", return_value=_settings()),
            patch.object(measurement_mqtt, "store_measurement_from_mqtt") as store,
        ):
            measurement_mqtt._on_message(None, None, message)

        store.assert_not_called()
        self.assertEqual(thermal_image.thermal_image_store.get().data, JPEG)

    def test_people_count_payload_still_uses_measurement_ingest(self):
        payload = {
            "version": 1,
            "action": "measurement_update",
            "source": "team-b",
            "timestamp": 1782288000,
            "sensor": {
                "id": "k2-area-01",
                "type": "area",
                "zone_id": "k2",
                "floor_level": 1,
            },
            "measurement": {
                "people_count": 4,
                "count_type": "snapshot",
            },
        }
        message = SimpleNamespace(
            topic="team-b/thermal/people_count",
            payload=json.dumps(payload).encode(),
        )
        with (
            patch.object(measurement_mqtt, "get_settings", return_value=_settings()),
            patch.object(measurement_mqtt, "store_measurement_from_mqtt") as store,
        ):
            measurement_mqtt._on_message(None, None, message)

        store.assert_called_once()
        self.assertEqual(store.call_args.args[0].measurement.people_count, 4)


class ThermalImageRouterTests(TestCase):
    def setUp(self):
        thermal_image.thermal_image_store.clear()

    def tearDown(self):
        thermal_image.thermal_image_store.clear()

    def test_latest_returns_404_while_waiting(self):
        with self.assertRaises(HTTPException) as context:
            thermal_image_router.latest_thermal_image()
        self.assertEqual(context.exception.status_code, 404)

    def test_latest_returns_raw_frame_headers(self):
        frame = thermal_image.thermal_image_store.replace(
            PNG,
            max_bytes=1024,
            received_at=datetime(2026, 6, 24, 8, 0),
        )
        response = thermal_image_router.latest_thermal_image()

        self.assertEqual(response.body, PNG)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["etag"], f'"{frame.revision}"')
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")

    def test_status_endpoint_exposes_frame_metadata(self):
        settings = _settings()
        frame = thermal_image.thermal_image_store.replace(JPEG, max_bytes=1024)
        with patch.object(thermal_image, "get_settings", return_value=settings):
            response = thermal_image_router.thermal_image_status()

        self.assertTrue(response.available)
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(response.size_bytes, len(JPEG))
        self.assertEqual(response.revision, frame.revision)
        self.assertEqual(response.topic, settings.mqtt_thermal_image_topic)
