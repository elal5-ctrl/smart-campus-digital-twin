from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pandas as pd
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.session import engine
from app.models import Entry

EntryKey = tuple[datetime, float, float, int, int]

REQUIRED_COLUMNS = {
    "Date",
    "Time",
    "Coordinates",
    "People Count",
    "Floor Level",
}
LEGACY_UTC_OFFSET = timedelta(hours=2)


def build_export_url() -> str:
    settings = get_settings()
    query = urlencode(
        {
            "format": "csv",
            "gid": settings.google_sheet_gid,
        }
    )
    return (
        "https://docs.google.com/spreadsheets/d/"
        f"{settings.google_sheet_id}/export?{query}"
    )


def load_sheet_data() -> pd.DataFrame:
    return pd.read_csv(build_export_url())


def parse_timestamp(date_value: Any, time_value: Any) -> datetime:
    if _is_missing(date_value) or _is_missing(time_value):
        raise ValueError("date or time is missing")

    parsed = pd.to_datetime(
        f"{str(date_value).strip()} {str(time_value).strip()}",
        dayfirst=True,
    )

    if pd.isna(parsed):
        raise ValueError("date or time could not be parsed")

    return parsed.to_pydatetime().replace(tzinfo=None)


def parse_excel_and_save() -> dict[str, Any]:
    df = load_sheet_data()
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        return {
            "status": "error",
            "message": "Sheet is missing required columns",
            "missing_columns": sorted(missing_columns),
        }

    imported_rows = 0
    skipped_rows = 0
    duplicate_rows = 0
    corrected_rows = 0
    deleted_rows = 0
    errors: list[dict[str, Any]] = []
    parsed_rows: list[dict[str, Any]] = []

    for row_number, row in enumerate(df.to_dict("records"), start=2):
        try:
            parsed_rows.append(_parse_row(row))
        except ValueError as error:
            skipped_rows += 1
            errors.append({"row": row_number, "error": str(error)})

    if errors:
        return {
            "status": "error",
            "message": "Sheet contains invalid rows; database was not changed",
            "imported_rows": 0,
            "skipped_rows": skipped_rows,
            "duplicate_rows": 0,
            "corrected_rows": 0,
            "deleted_rows": 0,
            "error_rows": len(errors),
            "errors": errors[:20],
        }

    with Session(engine) as session:
        existing_entries = _load_existing_entries(session)
        original_entries = existing_entries.copy()
        sheet_keys: set[EntryKey] = set()
        retained_entry_ids: set[int] = set()

        for parsed_row in parsed_rows:
            entry_key = _entry_key(**parsed_row)
            if entry_key in sheet_keys:
                duplicate_rows += 1
                skipped_rows += 1
                continue
            sheet_keys.add(entry_key)

            if entry_key in existing_entries:
                retained_entry_ids.add(existing_entries[entry_key])
                duplicate_rows += 1
                skipped_rows += 1
                continue

            legacy_key = _entry_key(
                timestamp=parsed_row["timestamp"] + LEGACY_UTC_OFFSET,
                latitude=parsed_row["latitude"],
                longitude=parsed_row["longitude"],
                total_count=parsed_row["total_count"],
                level=parsed_row["level"],
            )
            legacy_entry_id = existing_entries.get(legacy_key)
            if legacy_entry_id is not None:
                legacy_entry = session.get(Entry, legacy_entry_id)
                if legacy_entry is None:
                    continue

                legacy_entry.timestamp = parsed_row["timestamp"]
                existing_entries.pop(legacy_key)
                existing_entries[entry_key] = legacy_entry_id
                retained_entry_ids.add(legacy_entry_id)
                corrected_rows += 1
                continue

            session.add(
                Entry(
                    timestamp=parsed_row["timestamp"],
                    coordinates=from_shape(
                        Point(parsed_row["longitude"], parsed_row["latitude"]),
                        srid=4326,
                    ),
                    total_count=parsed_row["total_count"],
                    level=parsed_row["level"],
                )
            )
            existing_entries[entry_key] = -1
            imported_rows += 1

        for stale_entry_id in set(original_entries.values()) - retained_entry_ids:
            stale_entry = session.get(Entry, stale_entry_id)
            if stale_entry is not None:
                session.delete(stale_entry)
                deleted_rows += 1

        session.commit()

    return {
        "status": "ok",
        "message": (
            f"Imported {imported_rows} rows, corrected {corrected_rows} rows, "
            f"deleted {deleted_rows} obsolete rows"
        ),
        "imported_rows": imported_rows,
        "skipped_rows": skipped_rows,
        "duplicate_rows": duplicate_rows,
        "corrected_rows": corrected_rows,
        "deleted_rows": deleted_rows,
        "error_rows": len(errors),
        "errors": errors[:20],
    }


def _parse_row(row: dict[str, Any]) -> dict[str, Any]:
    latitude, longitude = _parse_coordinates(row["Coordinates"])
    total_count = _parse_non_negative_int(row["People Count"], "People Count")
    level = _parse_positive_int(row["Floor Level"], "Floor Level")

    return {
        "timestamp": parse_timestamp(row["Date"], row["Time"]),
        "latitude": latitude,
        "longitude": longitude,
        "total_count": total_count,
        "level": level,
    }


def _parse_coordinates(value: Any) -> tuple[float, float]:
    if _is_missing(value):
        raise ValueError("coordinates are missing")

    parts = str(value).split(",")
    if len(parts) != 2:
        raise ValueError("coordinates must use 'latitude, longitude' format")

    try:
        latitude = float(parts[0].strip())
        longitude = float(parts[1].strip())
    except ValueError as error:
        raise ValueError("coordinates must contain numeric values") from error

    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")

    return latitude, longitude


def _parse_non_negative_int(value: Any, field_name: str) -> int:
    parsed = _parse_int(value, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _parse_positive_int(value: Any, field_name: str) -> int:
    parsed = _parse_int(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def _parse_int(value: Any, field_name: str) -> int:
    if _is_missing(value):
        raise ValueError(f"{field_name} is missing")

    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error

    if not parsed.is_integer():
        raise ValueError(f"{field_name} must be a whole number")

    return int(parsed)


def _load_existing_entries(session: Session) -> dict[EntryKey, int]:
    statement = select(
        Entry.id,
        Entry.timestamp,
        Entry.total_count,
        Entry.level,
        func.ST_Y(Entry.coordinates).label("latitude"),
        func.ST_X(Entry.coordinates).label("longitude"),
    )

    existing_entries: dict[EntryKey, int] = {}
    for entry_id, timestamp, total_count, level, latitude, longitude in session.exec(
        statement
    ):
        if entry_id is None:
            continue

        existing_entries[
            _entry_key(
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
                total_count=total_count,
                level=level,
            )
        ] = entry_id

    return existing_entries


def _entry_key(
    *,
    timestamp: datetime,
    latitude: float,
    longitude: float,
    total_count: int,
    level: int,
) -> EntryKey:
    return (
        timestamp,
        round(latitude, 6),
        round(longitude, 6),
        total_count,
        level,
    )


def _is_missing(value: Any) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""
