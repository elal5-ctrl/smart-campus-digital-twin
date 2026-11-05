"""
database_referral.py - Extract generation patterns from database entries.

This module reads the backend `entries` table and builds a compact profile that
can be imported by gen_data.py while it runs. The CLI can still write the profile
to JSON for inspection, but gen_data.py does not need a file handoff.

The output is intentionally simple:
    - hourly_factors: traffic multiplier by weekday/weekend and hour
    - collection_times: observed fixed collection times by weekday/weekend
    - location_weights: traffic multiplier by rounded latitude/longitude
    - defaults: fallback values for hours/locations missing in the database

Examples:
    python database_referral.py -o database_profile.json
    python database_referral.py -o database_profile.json --round-coordinates 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def load_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    repo_root = Path(__file__).resolve().parents[1]
    backend_path = repo_root / "backend"
    sys.path.insert(0, str(backend_path))

    try:
        from app.core.config import get_settings
    except ImportError as error:
        raise RuntimeError(
            "DATABASE_URL is not set and backend settings could not be imported. "
            "Run this from the project environment or set DATABASE_URL."
        ) from error

    return get_settings().database_url


def load_entries_from_database() -> Any:
    import pandas as pd
    from sqlalchemy import create_engine, text

    query = text(
        """
        SELECT
            timestamp,
            total_count,
            level,
            ST_Y(coordinates) AS latitude,
            ST_X(coordinates) AS longitude
        FROM entries
        ORDER BY timestamp
        """
    )

    engine = create_engine(load_database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        return pd.read_sql_query(query, connection)


def build_generation_profile(df: Any, round_coordinates: int) -> dict[str, Any]:
    import pandas as pd

    if df.empty:
        raise RuntimeError("No rows found in entries table.")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["time_of_day"] = df["timestamp"].dt.strftime("%H:%M")
    df["day_type"] = df["timestamp"].dt.dayofweek.map(
        lambda day: "weekend" if day >= 5 else "weekday"
    )
    df["lat_key"] = df["latitude"].round(round_coordinates)
    df["lon_key"] = df["longitude"].round(round_coordinates)

    global_mean = max(float(df["total_count"].mean()), 1.0)

    hourly_totals = (
        df.groupby(["day_type", "hour"], as_index=False)["total_count"]
        .mean()
        .rename(columns={"total_count": "mean_count"})
    )
    hourly_factors: dict[str, dict[str, float]] = {"weekday": {}, "weekend": {}}
    for row in hourly_totals.to_dict("records"):
        hourly_factors[row["day_type"]][str(int(row["hour"]))] = round(
            max(float(row["mean_count"]) / global_mean, 0.05),
            4,
        )

    collection_time_totals = (
        df.groupby(["day_type", "time_of_day"], as_index=False)
        .size()
        .rename(columns={"size": "sample_count"})
    )
    collection_times: dict[str, list[dict[str, Any]]] = {"weekday": [], "weekend": []}
    for row in collection_time_totals.to_dict("records"):
        hour_text, minute_text = row["time_of_day"].split(":")
        collection_times[row["day_type"]].append(
            {
                "time": row["time_of_day"],
                "hour": int(hour_text),
                "minute": int(minute_text),
                "sample_count": int(row["sample_count"]),
            }
        )

    for day_type in collection_times:
        collection_times[day_type].sort(key=lambda item: (item["hour"], item["minute"]))

    location_totals = (
        df.groupby(["lat_key", "lon_key"], as_index=False)["total_count"]
        .mean()
        .rename(columns={"total_count": "mean_count"})
    )
    location_weights: dict[str, float] = {}
    for row in location_totals.to_dict("records"):
        key = (
            f"{row['lat_key']:.{round_coordinates}f},"
            f"{row['lon_key']:.{round_coordinates}f}"
        )
        location_weights[key] = round(
            max(float(row["mean_count"]) / global_mean, 0.05),
            4,
        )

    return {
        "metadata": {
            "source": "entries",
            "row_count": int(len(df)),
            "global_mean_count": round(global_mean, 4),
            "round_coordinates": round_coordinates,
            "timestamp_min": df["timestamp"].min().isoformat(),
            "timestamp_max": df["timestamp"].max().isoformat(),
        },
        "defaults": {
            "hourly_factor": 1.0,
            "location_weight": 1.0,
            "collection_times": [
                {"time": "08:30", "hour": 8, "minute": 30, "sample_count": 1},
                {"time": "12:30", "hour": 12, "minute": 30, "sample_count": 1},
                {"time": "18:30", "hour": 18, "minute": 30, "sample_count": 1},
            ],
        },
        "hourly_factors": hourly_factors,
        "collection_times": collection_times,
        "location_weights": location_weights,
    }


def load_generation_profile(round_coordinates: int = 6) -> dict[str, Any]:
    df = load_entries_from_database()
    return build_generation_profile(df, round_coordinates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a gen_data.py pattern profile from backend database entries."
    )
    parser.add_argument("-o", "--output", default="database_profile.json")
    parser.add_argument("--round-coordinates", type=int, default=6)
    args = parser.parse_args()

    profile = load_generation_profile(args.round_coordinates)

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(profile, file, indent=2, sort_keys=True)

    print(
        f"Wrote profile from {profile['metadata']['row_count']} database entries "
        f"to '{args.output}'."
    )


if __name__ == "__main__":
    main()
