from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from hashlib import sha256

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import Entry, SyntheticLocationMeasurement
from app.services.campus_time import campus_now, utc_now_naive
from app.services.fixedlocations import FIXED_LOCATIONS, nearest_fixed_location

SYNTHETIC_HOURS = range(24)
SYNTHETIC_INTERVAL_MINUTES = 15
SYNTHETIC_SLOTS_PER_DAY = 24 * 60 // SYNTHETIC_INTERVAL_MINUTES


@dataclass(frozen=True)
class GenerationProfile:
    global_mean: float
    slot_counts: dict[tuple[str, str, int], float]


def create_synthetic_measurements_table() -> None:
    SyntheticLocationMeasurement.__table__.create(engine, checkfirst=True)


def refresh_synthetic_location_measurements() -> int:
    settings = get_settings()
    if not settings.synthetic_generation_enabled:
        return 0

    with Session(engine) as session:
        generation_version = _effective_generation_version(
            session,
            settings.synthetic_generation_version,
        )
        if not _synthetic_refresh_required(
            session,
            days=settings.synthetic_generation_days,
            generation_version=generation_version,
        ):
            return 0

        profile = build_generation_profile(session)
        rows = generate_synthetic_rows(
            profile=profile,
            days=settings.synthetic_generation_days,
            generation_version=generation_version,
        )
        session.exec(
            text("TRUNCATE TABLE synthetic_location_measurements RESTART IDENTITY")
        )
        session.add_all(rows)
        session.commit()
        return len(rows)


def build_generation_profile(session: Session) -> GenerationProfile:
    entries = session.exec(
        select(
            Entry.timestamp,
            Entry.total_count,
            func.ST_Y(Entry.coordinates).label("latitude"),
            func.ST_X(Entry.coordinates).label("longitude"),
        ).order_by(Entry.timestamp)
    ).all()
    return _build_generation_profile_from_entries(list(entries))


def _build_generation_profile_from_entries(
    entries: list[tuple[datetime, int, float, float]],
) -> GenerationProfile:
    if not entries:
        return _default_profile()

    global_mean = max(
        sum(float(total_count or 0) for _, total_count, _, _ in entries) / len(entries),
        1.0,
    )
    buckets: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    campus_buckets: dict[tuple[str, int], list[int]] = defaultdict(list)

    for timestamp, total_count, latitude, longitude in entries:
        count = int(total_count or 0)
        day_type = _day_type(timestamp)
        slot = _quarter_hour_slot(timestamp)
        campus_buckets[(day_type, slot)].append(count)

        location = nearest_fixed_location(latitude, longitude)
        if location is not None:
            buckets[(location.id, day_type, slot)].append(count)

    slot_counts: dict[tuple[str, str, int], float] = {}
    for location in FIXED_LOCATIONS:
        for day_type in ("weekday", "weekend"):
            known = {
                slot: _mean(values, global_mean)
                for (location_id, bucket_day_type, slot), values in buckets.items()
                if location_id == location.id and bucket_day_type == day_type and values
            }
            campus_known = {
                slot: _mean(values, global_mean)
                for (bucket_day_type, slot), values in campus_buckets.items()
                if bucket_day_type == day_type and values
            }
            for slot in range(SYNTHETIC_SLOTS_PER_DAY):
                fallback = _interpolated_slot_value(campus_known, slot)
                if fallback is None:
                    fallback = global_mean * _fallback_quarter_hour_factor(
                        day_type, slot
                    )
                location_value = _interpolated_slot_value(known, slot)
                location_fallback = (
                    fallback
                    * _fallback_location_weight(location.id)
                    * _location_activity_multiplier(location.id, slot)
                )
                slot_counts[(location.id, day_type, slot)] = max(
                    0.0,
                    location_value if location_value is not None else location_fallback,
                )

    return GenerationProfile(
        global_mean=global_mean,
        slot_counts=slot_counts,
    )


def generate_synthetic_rows(
    *,
    profile: GenerationProfile,
    days: int,
    generation_version: str,
) -> list[SyntheticLocationMeasurement]:
    created_at = utc_now_naive()
    start_date = campus_now().date() - timedelta(days=max(days, 1) - 1)
    rows: list[SyntheticLocationMeasurement] = []

    for day_offset in range(max(days, 1)):
        current_date = start_date + timedelta(days=day_offset)
        day_type = "weekend" if current_date.weekday() >= 5 else "weekday"
        for hour in SYNTHETIC_HOURS:
            for minute in range(0, 60, SYNTHETIC_INTERVAL_MINUTES):
                source_timestamp = datetime.combine(
                    current_date,
                    time(hour=hour, minute=minute),
                )
                for location in FIXED_LOCATIONS:
                    count = _synthetic_count(
                        profile=profile,
                        location_id=location.id,
                        day_type=day_type,
                        slot=hour * (60 // SYNTHETIC_INTERVAL_MINUTES)
                        + minute // SYNTHETIC_INTERVAL_MINUTES,
                        day_offset=day_offset,
                    )
                    rows.append(
                        SyntheticLocationMeasurement(
                            source_timestamp=source_timestamp,
                            location_id=location.id,
                            location_name=location.name,
                            latitude=location.latitude,
                            longitude=location.longitude,
                            people_count=count,
                            generation_version=generation_version,
                            created_at=created_at,
                        )
                    )

    return rows


def get_latest_synthetic_measurements_by_location(
    session: Session,
) -> dict[str, SyntheticLocationMeasurement]:
    current_rows = _synthetic_measurements_at_or_before(
        session,
        current_campus_interval(),
    )
    if current_rows:
        return current_rows

    statement = select(SyntheticLocationMeasurement).order_by(
        SyntheticLocationMeasurement.source_timestamp.desc(),
        SyntheticLocationMeasurement.id.desc(),
    )
    latest: dict[str, SyntheticLocationMeasurement] = {}
    for measurement in session.exec(statement):
        if measurement.location_id not in latest:
            latest[measurement.location_id] = measurement
    return latest


def _synthetic_measurements_at_or_before(
    session: Session,
    source_timestamp: datetime,
) -> dict[str, SyntheticLocationMeasurement]:
    statement = (
        select(SyntheticLocationMeasurement)
        .where(SyntheticLocationMeasurement.source_timestamp <= source_timestamp)
        .order_by(
            SyntheticLocationMeasurement.source_timestamp.desc(),
            SyntheticLocationMeasurement.id.desc(),
        )
    )
    latest: dict[str, SyntheticLocationMeasurement] = {}
    for measurement in session.exec(statement):
        if measurement.location_id not in latest:
            latest[measurement.location_id] = measurement
        if len(latest) == len(FIXED_LOCATIONS):
            break
    return latest


def current_campus_interval() -> datetime:
    now = campus_now()
    minute = now.minute - now.minute % SYNTHETIC_INTERVAL_MINUTES
    return now.replace(minute=minute, second=0, microsecond=0, tzinfo=None)


def _synthetic_refresh_required(
    session: Session,
    *,
    days: int,
    generation_version: str,
) -> bool:
    expected_days = max(days, 1)
    expected_rows = (
        expected_days
        * len(SYNTHETIC_HOURS)
        * (60 // SYNTHETIC_INTERVAL_MINUTES)
        * len(FIXED_LOCATIONS)
    )
    start_date = campus_now().date() - timedelta(days=expected_days - 1)
    end_date = campus_now().date()
    start_timestamp = datetime.combine(start_date, time.min)
    end_timestamp = datetime.combine(end_date, time.max)
    count, minimum, maximum = session.exec(
        select(
            func.count(SyntheticLocationMeasurement.id),
            func.min(SyntheticLocationMeasurement.source_timestamp),
            func.max(SyntheticLocationMeasurement.source_timestamp),
        ).where(
            SyntheticLocationMeasurement.generation_version == generation_version,
            SyntheticLocationMeasurement.source_timestamp >= start_timestamp,
            SyntheticLocationMeasurement.source_timestamp <= end_timestamp,
        )
    ).one()
    return (
        int(count or 0) < expected_rows
        or minimum is None
        or maximum is None
        or minimum.date() > start_date
        or maximum.date() < end_date
    )


def _default_profile() -> GenerationProfile:
    return GenerationProfile(
        global_mean=12.0,
        slot_counts={
            (location.id, day_type, slot): (
                12.0
                * _fallback_location_weight(location.id)
                * _fallback_quarter_hour_factor(day_type, slot)
                * _location_activity_multiplier(location.id, slot)
            )
            for location in FIXED_LOCATIONS
            for day_type in ("weekday", "weekend")
            for slot in range(SYNTHETIC_SLOTS_PER_DAY)
        },
    )


def _synthetic_count(
    *,
    profile: GenerationProfile,
    location_id: str,
    day_type: str,
    slot: int,
    day_offset: int,
) -> int:
    base = _demo_shaped_count(profile, location_id, day_type, slot)
    deterministic_variance = (
        0.9 + ((sum(ord(char) for char in location_id) + day_offset + slot) % 7) / 30
    )
    shaped_count = base * deterministic_variance
    if shaped_count < 4:
        shaped_count += _low_traffic_location_offset(location_id, slot, day_offset)
    return max(0, int(round(shaped_count)))


def _low_traffic_location_offset(location_id: str, slot: int, day_offset: int) -> int:
    lower_id = location_id.lower()
    seed = sum((index + 1) * ord(char) for index, char in enumerate(location_id))
    offset = ((seed + slot * 3 + day_offset) % 5) - 2
    if any(marker in lower_id for marker in ("library", "cafeteria", "building-a")):
        offset += 1
    if any(marker in lower_id for marker in ("sports-field", "aeon-side")):
        offset -= 1
    return offset


def _demo_shaped_count(
    profile: GenerationProfile,
    location_id: str,
    day_type: str,
    slot: int,
) -> float:
    return profile.slot_counts.get(
        (location_id, day_type, slot),
        profile.slot_counts.get(
            (location_id, "weekday", slot),
            profile.global_mean * _fallback_location_weight(location_id),
        ),
    )


def _location_activity_multiplier(location_id: str, slot: int) -> float:
    fractional_hour = slot * SYNTHETIC_INTERVAL_MINUTES / 60
    lower_id = location_id.lower()
    if any(marker in lower_id for marker in ("gate", "entrance")) and (
        8 <= fractional_hour < 10 or 16 <= fractional_hour < 19
    ):
        return 1.18
    if (
        any(marker in lower_id for marker in ("cafeteria", "library"))
        and 11 <= fractional_hour < 15
    ):
        return 1.28
    if (
        any(marker in lower_id for marker in ("gym", "building-g"))
        and 15 <= fractional_hour < 19
    ):
        return 1.12
    return 1.0


def _day_type(timestamp: datetime) -> str:
    return "weekend" if timestamp.weekday() >= 5 else "weekday"


def _mean(values: list[int], fallback: float) -> float:
    if not values:
        return fallback
    return sum(values) / len(values)


def _quarter_hour_slot(timestamp: datetime) -> int:
    return (timestamp.hour * 60 + timestamp.minute) // SYNTHETIC_INTERVAL_MINUTES


def _interpolated_slot_value(
    known_values: dict[int, float],
    target_slot: int,
) -> float | None:
    if not known_values:
        return None
    if target_slot in known_values:
        return known_values[target_slot]
    previous_slots = [slot for slot in known_values if slot < target_slot]
    next_slots = [slot for slot in known_values if slot > target_slot]
    if not previous_slots or not next_slots:
        return None

    previous_slot = max(previous_slots)
    next_slot = min(next_slots)
    distance_from_previous = target_slot - previous_slot
    distance_to_next = next_slot - target_slot
    total_distance = distance_from_previous + distance_to_next
    if total_distance == 0:
        return known_values[previous_slot]
    ratio = distance_from_previous / total_distance
    return known_values[previous_slot] * (1.0 - ratio) + known_values[next_slot] * ratio


def _fallback_quarter_hour_factor(day_type: str, slot: int) -> float:
    fractional_hour = slot * SYNTHETIC_INTERVAL_MINUTES / 60
    lower_hour = int(fractional_hour) % 24
    upper_hour = (lower_hour + 1) % 24
    fraction = fractional_hour - int(fractional_hour)
    return (
        _fallback_hourly_factor(day_type, lower_hour) * (1.0 - fraction)
        + _fallback_hourly_factor(day_type, upper_hour) * fraction
    )


def _effective_generation_version(session: Session, base_version: str) -> str:
    count, maximum_id, maximum_timestamp, total_count = session.exec(
        select(
            func.count(Entry.id),
            func.max(Entry.id),
            func.max(Entry.timestamp),
            func.sum(Entry.total_count),
        )
    ).one()
    source = "|".join(
        (
            str(int(count or 0)),
            str(int(maximum_id or 0)),
            maximum_timestamp.isoformat() if maximum_timestamp is not None else "",
            str(int(total_count or 0)),
        )
    )
    digest = sha256(source.encode("utf-8")).hexdigest()[:12]
    return f"{base_version}-{digest}"


def _fallback_hourly_factor(day_type: str, hour: int) -> float:
    if day_type == "weekend":
        if 10 <= hour <= 18:
            return 0.35
        if 7 <= hour <= 22:
            return 0.16
        return 0.08
    if hour in {8, 9, 12, 13, 16, 17}:
        return 1.7
    if 10 <= hour <= 15:
        return 0.85
    if hour in {7, 18, 19}:
        return 0.45
    if 20 <= hour <= 22:
        return 0.18
    return 0.08


def _fallback_location_weight(location_id: str) -> float:
    high_weight_markers = ("entrance", "gate")
    medium_weight_markers = ("library", "cafeteria", "building-a")
    if any(marker in location_id for marker in high_weight_markers):
        return 1.3
    if any(marker in location_id for marker in medium_weight_markers):
        return 1.1
    return 0.8
