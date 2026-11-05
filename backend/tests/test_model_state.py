from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import model_state
from app.services.fixedlocations import (
    EXTERNAL_SENSOR_LOCATION_IDS,
    FIXED_LOCATIONS,
    PHYSICAL_MODEL_LOCATIONS,
)


class ModelStatePayloadTests(TestCase):
    def test_locations_payload_excludes_external_sensor_locations(self):
        synthetic = {
            location.id: SimpleNamespace(
                people_count=5,
                source_timestamp=datetime(2026, 6, 23, 8, 0),
            )
            for location in FIXED_LOCATIONS
        }

        with (
            patch.object(
                model_state, "get_latest_measurements_by_sensor", return_value=[]
            ),
            patch.object(
                model_state,
                "get_latest_synthetic_measurements_by_location",
                return_value=synthetic,
            ),
            patch.object(
                model_state, "get_latest_predictions_by_location", return_value={}
            ),
        ):
            payload = model_state.build_locations_payload(session=object())

        self.assertEqual(payload["type"], "locations")
        self.assertEqual(payload["source"], "simulated")
        payload_ids = {item["id"] for item in payload["payload"]}
        self.assertEqual(len(payload["payload"]), len(PHYSICAL_MODEL_LOCATIONS))
        self.assertTrue(payload_ids.isdisjoint(EXTERNAL_SENSOR_LOCATION_IDS))
        self.assertEqual(payload["payload"][0]["source"], "simulated")

    def test_nodes_payload_marks_k1_live_when_measurement_exists(self):
        measurement = SimpleNamespace(
            sensor_id="k1-light-barrier-01",
            people_count=3,
            source_timestamp=datetime(2026, 6, 23, 8, 0),
        )

        with (
            patch.object(
                model_state,
                "get_latest_measurements_by_sensor",
                return_value=[measurement],
            ),
            patch.object(
                model_state,
                "get_latest_synthetic_measurements_by_location",
                return_value={},
            ),
        ):
            payload = model_state.build_nodes_payload(session=object())

        k1 = next(item for item in payload["payload"] if item["id"] == "k1")
        self.assertEqual(k1["status"], "live")
        self.assertEqual(k1["value"], 3)
