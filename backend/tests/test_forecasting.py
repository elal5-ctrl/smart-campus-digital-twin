from datetime import datetime, timedelta
from math import pi, sin
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlmodel import Session, create_engine

from app.models import (
    SyntheticLocationMeasurement,
    TeamBMeasurement,
    TrafficPrediction,
)
from app.services import (
    campus_time,
    fourier_forecasting,
    predictions,
    synthetic_data,
)
from app.services.fixedlocations import (
    FIXED_LOCATIONS,
    FIXED_LOCATIONS_BY_ID,
    LOCATION_RADIUS_METERS,
    SENSOR_FIXED_LOCATION_MAP,
    _distance_meters,
)
from app.services.measurements import (
    get_latest_measurements_by_sensor,
    is_measurement_fresh,
)


class CampusTimeTests(TestCase):
    def test_utc_crosses_into_next_day_in_japan(self):
        with patch.object(
            campus_time,
            "get_settings",
            return_value=SimpleNamespace(weather_timezone="Asia/Tokyo"),
        ):
            converted = campus_time.utc_naive_to_campus(datetime(2026, 6, 23, 23, 30))

        self.assertEqual(converted.date().isoformat(), "2026-06-24")
        self.assertEqual((converted.hour, converted.minute), (8, 30))


class SyntheticDataTests(TestCase):
    def test_generation_covers_all_24_hours(self):
        rows = synthetic_data.generate_synthetic_rows(
            profile=synthetic_data._default_profile(),
            days=1,
            generation_version="test",
        )

        self.assertEqual(
            len(rows),
            24
            * (60 // synthetic_data.SYNTHETIC_INTERVAL_MINUTES)
            * len(FIXED_LOCATIONS),
        )
        self.assertEqual({row.source_timestamp.hour for row in rows}, set(range(24)))
        self.assertEqual(
            {row.source_timestamp.minute for row in rows},
            {0, 15, 30, 45},
        )
        self.assertTrue(all(row.people_count >= 0 for row in rows))

    def test_quarter_hour_profile_interpolates_sparse_slots(self):
        values = {32: 8.0, 36: 12.0}

        interpolated = synthetic_data._interpolated_slot_value(values, 34)

        self.assertEqual(interpolated, 10.0)

    def test_quarter_hour_profile_does_not_wrap_across_midnight(self):
        values = {32: 8.0, 72: 12.0}

        before_first_observation = synthetic_data._interpolated_slot_value(values, 4)
        after_last_observation = synthetic_data._interpolated_slot_value(values, 84)

        self.assertIsNone(before_first_observation)
        self.assertIsNone(after_last_observation)

    def test_entries_shape_quarter_hour_location_profile(self):
        location = FIXED_LOCATIONS[0]
        entries = [
            (datetime(2026, 6, 22, 8, 0), 10, location.latitude, location.longitude),
            (
                datetime(2026, 6, 22, 8, 15),
                30,
                location.latitude,
                location.longitude,
            ),
        ]

        profile = synthetic_data._build_generation_profile_from_entries(entries)

        self.assertEqual(profile.slot_counts[(location.id, "weekday", 32)], 10)
        self.assertEqual(profile.slot_counts[(location.id, "weekday", 33)], 30)

    def test_quarter_hour_counts_use_fractional_slots(self):
        location_id = FIXED_LOCATIONS[0].id
        profile = synthetic_data.GenerationProfile(
            global_mean=1,
            slot_counts={
                (location_id, "weekday", 32): 10,
                (location_id, "weekday", 33): 30,
            },
        )

        at_eight = synthetic_data._synthetic_count(
            profile=profile,
            location_id=location_id,
            day_type="weekday",
            slot=32,
            day_offset=0,
        )
        at_quarter_past = synthetic_data._synthetic_count(
            profile=profile,
            location_id=location_id,
            day_type="weekday",
            slot=33,
            day_offset=0,
        )

        self.assertNotEqual(at_eight, at_quarter_past)


class FixedLocationTests(TestCase):
    def test_k1_and_k2_use_separate_sensor_entrances(self):
        self.assertEqual(
            SENSOR_FIXED_LOCATION_MAP["k1"],
            "k1-south-west-campus-entrance",
        )
        self.assertEqual(
            SENSOR_FIXED_LOCATION_MAP["k2"],
            "k2-library-b-sensor-entrance",
        )

    def test_k1_uses_south_west_entrance_coordinates(self):
        location = FIXED_LOCATIONS_BY_ID["k1-south-west-campus-entrance"]

        self.assertAlmostEqual(location.latitude, 34.8089451)
        self.assertAlmostEqual(location.longitude, 135.5598084)

    def test_ordinary_new_entrances_are_outside_original_location_radius(self):
        ordinary_new_ids = {
            "west-sports-field-entrance",
            "east-campus-aeon-side-entrance",
        }
        excluded_ids = ordinary_new_ids | {
            "k1-south-west-campus-entrance",
            "k2-library-b-sensor-entrance",
        }
        existing = [
            location for location in FIXED_LOCATIONS if location.id not in excluded_ids
        ]

        for location_id in ordinary_new_ids:
            location = FIXED_LOCATIONS_BY_ID[location_id]
            nearest_distance = min(
                _distance_meters(
                    location.latitude,
                    location.longitude,
                    other.latitude,
                    other.longitude,
                )
                for other in existing
            )
            self.assertGreater(nearest_distance, LOCATION_RADIUS_METERS)


class FourierForecastingTests(TestCase):
    def tearDown(self):
        fourier_forecasting.clear_fourier_cache()

    def test_fit_uses_fractional_hours(self):
        samples = [
            (
                slot / 4,
                20 + 10 * sin(2 * pi * (slot / 4) / 24),
            )
            for slot in range(96)
        ]
        model = fourier_forecasting.fit_fourier_model(
            samples,
            harmonics=6,
            ridge_alpha=1.0,
            minimum_samples=26,
        )

        self.assertIsNotNone(model)
        models = {("location", "weekday"): model}
        at_midnight = fourier_forecasting.predict_fourier_count(
            models,
            location_id="location",
            timestamp=datetime(2026, 6, 24, 0, 0),
            harmonics=6,
        )
        at_quarter_past = fourier_forecasting.predict_fourier_count(
            models,
            location_id="location",
            timestamp=datetime(2026, 6, 24, 0, 15),
            harmonics=6,
        )

        self.assertNotEqual(at_midnight, at_quarter_past)

    def test_insufficient_samples_do_not_create_model(self):
        model = fourier_forecasting.fit_fourier_model(
            [(hour, 5.0) for hour in range(10)],
            harmonics=6,
            ridge_alpha=1.0,
            minimum_samples=26,
        )

        self.assertIsNone(model)

    def test_model_cache_invalidates_when_synthetic_rows_change(self):
        engine = create_engine("sqlite://")
        SyntheticLocationMeasurement.__table__.create(engine)
        settings = SimpleNamespace(
            predictions_fourier_harmonics=1,
            predictions_fourier_ridge_alpha=1.0,
            predictions_fourier_minimum_samples=2,
        )
        with Session(engine) as session:
            session.add_all(
                [
                    _synthetic_measurement(datetime(2026, 6, 22, 8, 0), 5),
                    _synthetic_measurement(datetime(2026, 6, 22, 8, 15), 7),
                ]
            )
            session.commit()

            with patch.object(
                fourier_forecasting,
                "get_settings",
                return_value=settings,
            ):
                first = fourier_forecasting.get_fourier_models(session)
                second = fourier_forecasting.get_fourier_models(session)
                session.add(_synthetic_measurement(datetime(2026, 6, 22, 8, 30), 9))
                session.commit()
                third = fourier_forecasting.get_fourier_models(session)

        self.assertIs(first, second)
        self.assertIsNot(second, third)


class MeasurementFreshnessTests(TestCase):
    def test_measurement_older_than_freshness_window_is_stale(self):
        now = datetime(2026, 6, 24, 8, 0)
        measurement = TeamBMeasurement(
            received_at=now - timedelta(minutes=16),
            source_timestamp=now - timedelta(minutes=16),
            version=1,
            action="measurement_update",
            source="team-b",
            sensor_id="k1",
            sensor_type="light_barrier",
            zone_id="k1",
            floor_level=1,
            people_count=3,
            count_type="snapshot",
        )

        with patch(
            "app.services.measurements.get_settings",
            return_value=SimpleNamespace(team_b_measurement_freshness_minutes=15),
        ):
            self.assertFalse(is_measurement_fresh(measurement, now=now))

    def test_latest_measurements_excludes_stale_sensor_rows(self):
        now = datetime(2026, 6, 24, 8, 0)
        engine = create_engine("sqlite://")
        TeamBMeasurement.__table__.create(engine)
        with Session(engine) as session:
            session.add(
                _measurement("fresh", now - timedelta(minutes=5), people_count=4)
            )
            session.add(
                _measurement("stale", now - timedelta(minutes=20), people_count=9)
            )
            session.commit()

            with patch(
                "app.services.measurements.get_settings",
                return_value=SimpleNamespace(team_b_measurement_freshness_minutes=15),
            ):
                measurements = get_latest_measurements_by_sensor(session, now=now)

        self.assertEqual([item.sensor_id for item in measurements], ["fresh"])


class PredictionTests(TestCase):
    def test_prediction_generation_uses_japanese_hour(self):
        generated_at = datetime(2026, 6, 23, 23, 0)
        synthetic = {
            location.id: SimpleNamespace(people_count=4) for location in FIXED_LOCATIONS
        }
        profile = {
            (location.id, "weekday", slot): count
            for location in FIXED_LOCATIONS
            for slot, count in ((32, 7), (36, 9))
        }
        settings = SimpleNamespace(
            predictions_horizon_hours=2,
            predictions_model_version="test",
            predictions_fourier_harmonics=6,
            predictions_sunny_boost=0.08,
            predictions_rainy_penalty=0.20,
        )

        with (
            patch.object(predictions, "utc_now_naive", return_value=generated_at),
            patch.object(predictions, "get_settings", return_value=settings),
            patch.object(predictions, "_latest_weather", return_value=None),
            patch.object(
                predictions,
                "_latest_real_counts_by_location",
                return_value={},
            ),
            patch.object(
                predictions,
                "get_latest_synthetic_measurements_by_location",
                return_value=synthetic,
            ),
            patch.object(
                predictions,
                "_synthetic_profile_by_location_and_slot",
                return_value=profile,
            ),
            patch.object(predictions, "get_fourier_models", return_value={}),
            patch.object(
                campus_time,
                "get_settings",
                return_value=SimpleNamespace(weather_timezone="Asia/Tokyo"),
            ),
        ):
            rows = predictions.build_prediction_rows(session=object())

        location_id = FIXED_LOCATIONS[0].id
        current = next(
            row
            for row in rows
            if row.location_id == location_id and row.target_timestamp == generated_at
        )
        one_hour = next(
            row
            for row in rows
            if row.location_id == location_id
            and row.target_timestamp == generated_at + timedelta(hours=1)
        )
        self.assertEqual(current.weather_adjusted_count, 7)
        self.assertEqual(one_hour.weather_adjusted_count, 9)

    def test_live_count_blends_before_weather_adjustment(self):
        generated_at = datetime(2026, 6, 23, 23, 0)
        location_id = FIXED_LOCATIONS[0].id
        synthetic = {
            location.id: SimpleNamespace(people_count=4) for location in FIXED_LOCATIONS
        }
        profile = {(location.id, "weekday", 32): 4 for location in FIXED_LOCATIONS}
        settings = SimpleNamespace(
            predictions_horizon_hours=1,
            predictions_model_version="test",
            predictions_fourier_harmonics=6,
            predictions_sunny_boost=0.08,
            predictions_rainy_penalty=0.20,
        )

        with (
            patch.object(predictions, "utc_now_naive", return_value=generated_at),
            patch.object(predictions, "get_settings", return_value=settings),
            patch.object(
                predictions,
                "_latest_weather",
                return_value=SimpleNamespace(condition="sunny"),
            ),
            patch.object(
                predictions,
                "_latest_real_counts_by_location",
                return_value={location_id: 20},
            ),
            patch.object(
                predictions,
                "get_latest_synthetic_measurements_by_location",
                return_value=synthetic,
            ),
            patch.object(
                predictions,
                "_synthetic_profile_by_location_and_slot",
                return_value=profile,
            ),
            patch.object(predictions, "get_fourier_models", return_value={}),
            patch.object(
                predictions,
                "predict_fourier_count",
                side_effect=lambda _, location_id, **__: (
                    10 if location_id == FIXED_LOCATIONS[0].id else None
                ),
            ),
            patch.object(
                campus_time,
                "get_settings",
                return_value=SimpleNamespace(weather_timezone="Asia/Tokyo"),
            ),
        ):
            rows = predictions.build_prediction_rows(session=object())

        row = next(item for item in rows if item.location_id == location_id)
        self.assertEqual(row.base_count, 10)
        self.assertEqual(row.predicted_count, 15)
        self.assertEqual(row.weather_adjusted_count, 16)

    def test_one_hour_selection_chooses_nearest_target_per_location(self):
        target = datetime(2026, 6, 24, 0, 0)
        rows = [
            _prediction("a", target - timedelta(minutes=15), 3),
            _prediction("a", target, 8),
            _prediction("b", target + timedelta(minutes=15), 5),
        ]

        selected = predictions._predictions_nearest_target(rows, target)

        self.assertEqual(selected["a"].weather_adjusted_count, 8)
        self.assertEqual(selected["b"].weather_adjusted_count, 5)

    def test_latest_reads_use_only_newest_prediction_batch(self):
        now = datetime(2026, 6, 23, 23, 0)
        old_generated_at = now - timedelta(minutes=30)
        engine = create_engine("sqlite://")
        TrafficPrediction.__table__.create(engine)
        with Session(engine) as session:
            session.add(
                _prediction(
                    "a",
                    now + timedelta(minutes=45),
                    99,
                    generated_at=old_generated_at,
                )
            )
            session.add(
                _prediction(
                    "a",
                    now + timedelta(hours=1),
                    8,
                    generated_at=now,
                )
            )
            session.add(
                _prediction(
                    "b",
                    now + timedelta(hours=1),
                    5,
                    generated_at=now,
                )
            )
            session.commit()

            with patch.object(predictions, "utc_now_naive", return_value=now):
                latest = predictions.get_latest_predictions_by_location(session)
                totals = predictions.get_prediction_totals(session)

        self.assertEqual(latest["a"].weather_adjusted_count, 8)
        self.assertEqual(latest["b"].weather_adjusted_count, 5)
        self.assertEqual(totals, [13])


def _prediction(
    location_id: str,
    target_timestamp: datetime,
    count: int,
    *,
    generated_at: datetime = datetime(2026, 6, 23, 23, 0),
) -> TrafficPrediction:
    return TrafficPrediction(
        generated_at=generated_at,
        target_timestamp=target_timestamp,
        location_id=location_id,
        location_name=location_id,
        latitude=0,
        longitude=0,
        base_count=count,
        predicted_count=count,
        weather_adjusted_count=count,
        weather_condition=None,
        weather_multiplier=1,
        model_version="test",
    )


def _measurement(
    sensor_id: str,
    received_at: datetime,
    *,
    people_count: int,
) -> TeamBMeasurement:
    return TeamBMeasurement(
        received_at=received_at,
        source_timestamp=received_at,
        version=1,
        action="measurement_update",
        source="team-b",
        sensor_id=sensor_id,
        sensor_type="area",
        zone_id=sensor_id,
        floor_level=1,
        people_count=people_count,
        count_type="snapshot",
    )


def _synthetic_measurement(
    source_timestamp: datetime,
    people_count: int,
) -> SyntheticLocationMeasurement:
    return SyntheticLocationMeasurement(
        source_timestamp=source_timestamp,
        location_id="location",
        location_name="Location",
        latitude=0,
        longitude=0,
        people_count=people_count,
        generation_version="test",
        created_at=datetime(2026, 6, 24, 8, 0),
    )
