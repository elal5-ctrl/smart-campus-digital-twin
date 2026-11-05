"""
weather_adjusted_traffic.py - Fourier prediction with a simple weather switch.

This script keeps the existing Fourier model as the main signal and applies one
small weather adjustment:

    sunny   -> configurable positive multiplier
    rainy   -> configurable negative multiplier
    neutral -> no adjustment

It intentionally avoids fitting a regression model because the available data is
small. In auto mode it uses Open-Meteo. Forecast dates use the forecast API;
past dates use the archive API. You can also pass the weather state manually for
demos/tests.

Output goes to both a CSV file and a PostgreSQL table. All database connection
details are set via the DB_* placeholders near the top of this file.

Continuous mode (--continuous) keeps the process alive: after each generation
cycle it sleeps until the next OUTPUT_FREQUENCY_MINUTES boundary, then runs
again with a window anchored to that moment.

Examples:
    # One-shot, CSV + DB
    python weather_adjusted_traffic.py -f weights.npz -S 2026-05-15 -E 2026-05-15T22:00:00 -o weather_output.csv

    # One-shot, CSV only (skip DB write)
    python weather_adjusted_traffic.py -f weights.npz -S 2026-05-15 -E 2026-05-15T22:00:00 -o weather_output.csv --no-db

    # Force weather state manually
    python weather_adjusted_traffic.py -f weights.npz -S 2026-05-15 -E 2026-05-15T22:00:00 --weather rainy -o weather_output.csv

    # Continuous mode: generates data every 15 minutes, window starts at a fixed point
    python weather_adjusted_traffic.py -f weights.npz --continuous -S 2026-05-15 -o weather_output.csv
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from urllib.request import urlopen

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


# ---------------------------------------------------------------------------
# General config
# ---------------------------------------------------------------------------
OUTPUT_FREQUENCY_MINUTES = 15
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_LATITUDE = 34.8102
DEFAULT_LONGITUDE = 135.5616
DEFAULT_TIMEZONE = "Asia/Tokyo"

# ---------------------------------------------------------------------------
# PostgreSQL connection placeholders
# Fill these in (or override via environment variables / a secrets manager).
# ---------------------------------------------------------------------------
DB_HOST     = "localhost"       # e.g. "db.example.com" or an RDS endpoint
DB_PORT     = 5432              # default PostgreSQL port
DB_NAME     = "your_db_name"   # name of the target database
DB_USER     = "your_db_user"   # database user
DB_PASSWORD = "your_password"  # database password

# The table that predictions will be written to.
# The table is created automatically on first run if it does not exist.
DB_TABLE    = "weather_traffic_predictions"

# ---------------------------------------------------------------------------
# Weather codes
# ---------------------------------------------------------------------------
SUNNY_WEATHER_CODES = {0, 1}
RAINY_WEATHER_CODES = {
    51, 53, 55, 56, 57,
    61, 63, 65, 66, 67,
    80, 81, 82,
    95, 96, 99,
}


# ---------------------------------------------------------------------------
# Weather helpers
# ---------------------------------------------------------------------------

def classify_weather(
    weather_code: int | None,
    rain_chance_pct: int | None,
    rain_threshold_pct: int,
) -> str:
    if rain_chance_pct is not None and int(rain_chance_pct) >= rain_threshold_pct:
        return "rainy"
    if weather_code in SUNNY_WEATHER_CODES:
        return "sunny"
    if weather_code in RAINY_WEATHER_CODES:
        return "rainy"
    return "neutral"


def fetch_weather_by_date(
    *,
    start_date: date,
    end_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
    rain_threshold_pct: int,
) -> dict[date, dict[str, Any]]:
    import pandas as pd

    today = pd.Timestamp.today().date()
    daily_weather: dict[date, dict[str, Any]] = {}

    if start_date <= today:
        archive_end = min(end_date, today)
        daily_weather.update(
            fetch_archive_weather(
                start_date=start_date,
                end_date=archive_end,
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                rain_threshold_pct=rain_threshold_pct,
            )
        )

    if end_date >= today:
        forecast_start = max(start_date, today)
        daily_weather.update(
            fetch_forecast_weather(
                start_date=forecast_start,
                end_date=end_date,
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                rain_threshold_pct=rain_threshold_pct,
            )
        )

    return daily_weather


def fetch_forecast_weather(
    *,
    start_date: date,
    end_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
    rain_threshold_pct: int,
) -> dict[date, dict[str, Any]]:
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "weather_code,precipitation_probability_max",
            "timezone": timezone,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
    )
    return parse_daily_weather_response(
        url=f"{FORECAST_URL}?{query}",
        source="forecast",
        rain_threshold_pct=rain_threshold_pct,
    )


def fetch_archive_weather(
    *,
    start_date: date,
    end_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
    rain_threshold_pct: int,
) -> dict[date, dict[str, Any]]:
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "weather_code,precipitation_sum",
            "timezone": timezone,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
    )
    return parse_daily_weather_response(
        url=f"{ARCHIVE_URL}?{query}",
        source="archive",
        rain_threshold_pct=rain_threshold_pct,
    )


def parse_daily_weather_response(
    *,
    url: str,
    source: str,
    rain_threshold_pct: int,
) -> dict[date, dict[str, Any]]:
    with urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise RuntimeError(f"Weather API response from {source} has no daily block.")

    dates = daily.get("time") or []
    weather_codes = daily.get("weather_code") or []
    rain_chances = daily.get("precipitation_probability_max")
    precipitation_sums = daily.get("precipitation_sum")

    weather_by_date: dict[date, dict[str, Any]] = {}
    for index, date_text in enumerate(dates):
        weather_code = optional_int_at(weather_codes, index)

        if rain_chances is not None:
            rain_chance_pct = optional_int_at(rain_chances, index)
            precipitation_mm = None
        else:
            precipitation_mm = optional_float_at(precipitation_sums or [], index)
            rain_chance_pct = 100 if precipitation_mm and precipitation_mm > 0 else 0

        weather_switch = classify_weather(weather_code, rain_chance_pct, rain_threshold_pct)
        weather_by_date[date.fromisoformat(date_text)] = {
            "source": source,
            "weather_code": weather_code,
            "rain_chance_pct": rain_chance_pct,
            "precipitation_mm": precipitation_mm,
            "weather_switch": weather_switch,
        }

    return weather_by_date


def optional_int_at(values: list[Any], index: int) -> int | None:
    if index >= len(values) or values[index] is None:
        return None
    return int(values[index])


def optional_float_at(values: list[Any], index: int) -> float | None:
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def weather_multiplier(weather: str, sunny_boost: float, rainy_penalty: float) -> float:
    if weather == "sunny":
        return 1.0 + sunny_boost
    if weather == "rainy":
        return max(0.0, 1.0 - rainy_penalty)
    return 1.0


# ---------------------------------------------------------------------------
# Fourier model
# ---------------------------------------------------------------------------

def load_fourier_archive(
    npz_file_path: str,
) -> tuple[dict[int, tuple[np.ndarray, int]], dict[int, float], dict[int, float], dict[int, float]]:
    import numpy as np

    archive = np.load(npz_file_path, allow_pickle=True)
    node_ids = sorted(
        int(key[len("coeffs_"):])
        for key in archive.files
        if key.startswith("coeffs_")
    )

    models: dict[int, tuple[np.ndarray, int]] = {}
    latitudes: dict[int, float] = {}
    longitudes: dict[int, float] = {}
    count_caps: dict[int, float] = {}

    for node_id in node_ids:
        models[node_id] = (
            archive[f"coeffs_{node_id}"],
            int(archive[f"harmonics_{node_id}"]),
        )
        latitudes[node_id] = float(archive[f"latitude_{node_id}"])
        longitudes[node_id] = float(archive[f"longitude_{node_id}"])
        count_caps[node_id] = float(archive[f"count_cap_{node_id}"])

    return models, latitudes, longitudes, count_caps


def build_fourier_features(
    time_in_hours: np.ndarray,
    harmonic_count: int,
    period_hours: float = 24.0,
) -> np.ndarray:
    import numpy as np

    columns = [np.ones(len(time_in_hours))]
    for harmonic_index in range(1, harmonic_count + 1):
        angle = 2 * np.pi * harmonic_index * time_in_hours / period_hours
        columns.append(np.sin(angle))
        columns.append(np.cos(angle))
    return np.column_stack(columns)


def predict_node_counts(
    model: tuple[np.ndarray, int],
    timestamps: pd.DatetimeIndex,
    count_cap: float,
) -> np.ndarray:
    import numpy as np

    coefficients, harmonic_count = model
    hours = np.array([ts.hour + ts.minute / 60.0 for ts in timestamps])
    design_matrix = build_fourier_features(hours, harmonic_count)
    return np.clip(design_matrix @ coefficients, 0, count_cap)


def generate_weather_adjusted_predictions(
    npz_file_path: str,
    start: str,
    end: str,
    weather_by_date: dict[date, dict[str, Any]],
    sunny_boost: float,
    rainy_penalty: float,
) -> pd.DataFrame:
    import pandas as pd

    models, latitudes, longitudes, count_caps = load_fourier_archive(npz_file_path)
    timestamps = pd.date_range(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        freq=f"{OUTPUT_FREQUENCY_MINUTES}min",
    )

    rows: list[dict[str, Any]] = []
    for node_id, model in models.items():
        base_counts = predict_node_counts(model, timestamps, count_caps[node_id])

        for timestamp, base_count in zip(timestamps, base_counts):
            weather_info = weather_by_date.get(
                timestamp.date(),
                {"weather_switch": "neutral", "rain_chance_pct": None, "source": "missing"},
            )
            weather = weather_info["weather_switch"]
            multiplier = weather_multiplier(weather, sunny_boost, rainy_penalty)
            adjusted_count = int(round(float(base_count) * multiplier))

            rows.append(
                {
                    "node_id": node_id,
                    "Timestamp": timestamp,
                    "Latitude": latitudes[node_id],
                    "Longitude": longitudes[node_id],
                    "FourierCount": int(round(float(base_count))),
                    "WeatherAdjustedCount": int(adjusted_count),
                    "WeatherSwitch": weather,
                    "RainChancePct": weather_info["rain_chance_pct"],
                    "WeatherSource": weather_info["source"],
                    "WeatherMultiplier": round(multiplier, 4),
                }
            )

    output = pd.DataFrame(rows).sort_values(["node_id", "Timestamp"]).reset_index(drop=True)
    output.insert(0, "Primary key", range(1, len(output) + 1))
    output["Timestamp"] = output["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return output


# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Return a new psycopg2 connection using the DB_* config at the top of this file."""
    import psycopg2  # pip install psycopg2-binary

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def ensure_table_exists(conn) -> None:
    """Create DB_TABLE if it does not already exist."""
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {DB_TABLE} (
        primary_key          BIGSERIAL PRIMARY KEY,
        node_id              BIGINT        NOT NULL,
        timestamp            TIMESTAMP     NOT NULL,
        latitude             DOUBLE PRECISION NOT NULL,
        longitude            DOUBLE PRECISION NOT NULL,
        fourier_count        INTEGER       NOT NULL,
        weather_adjusted_count INTEGER     NOT NULL,
        weather_switch       VARCHAR(16)   NOT NULL,
        rain_chance_pct      INTEGER,
        weather_source       VARCHAR(32),
        weather_multiplier   DOUBLE PRECISION NOT NULL,
        inserted_at          TIMESTAMP     NOT NULL DEFAULT NOW(),

        -- Natural uniqueness: one prediction row per node per 15-min slot.
        CONSTRAINT uq_{DB_TABLE}_node_ts UNIQUE (node_id, timestamp)
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def write_to_postgres(df: pd.DataFrame) -> int:
    """
    Upsert all rows from *df* into DB_TABLE.

    On conflict (node_id, timestamp) the row is updated in place so that
    re-running the script for an overlapping window is safe.

    Returns the number of rows written.
    """
    import psycopg2.extras

    upsert_sql = f"""
    INSERT INTO {DB_TABLE} (
        node_id, timestamp, latitude, longitude,
        fourier_count, weather_adjusted_count,
        weather_switch, rain_chance_pct, weather_source, weather_multiplier
    ) VALUES %s
    ON CONFLICT (node_id, timestamp) DO UPDATE SET
        latitude               = EXCLUDED.latitude,
        longitude              = EXCLUDED.longitude,
        fourier_count          = EXCLUDED.fourier_count,
        weather_adjusted_count = EXCLUDED.weather_adjusted_count,
        weather_switch         = EXCLUDED.weather_switch,
        rain_chance_pct        = EXCLUDED.rain_chance_pct,
        weather_source         = EXCLUDED.weather_source,
        weather_multiplier     = EXCLUDED.weather_multiplier,
        inserted_at            = NOW();
    """

    rows = [
        (
            int(row["node_id"]),
            row["Timestamp"],               # already a string "YYYY-MM-DD HH:MM:SS"
            float(row["Latitude"]),
            float(row["Longitude"]),
            int(row["FourierCount"]),
            int(row["WeatherAdjustedCount"]),
            row["WeatherSwitch"],
            row["RainChancePct"],           # may be None
            row["WeatherSource"],
            float(row["WeatherMultiplier"]),
        )
        for _, row in df.iterrows()
    ]

    conn = get_db_connection()
    try:
        ensure_table_exists(conn)
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, upsert_sql, rows, page_size=500)
        conn.commit()
    finally:
        conn.close()

    return len(rows)


# ---------------------------------------------------------------------------
# Timing helpers for continuous mode
# ---------------------------------------------------------------------------

def next_interval_start(now: datetime, interval_minutes: int) -> datetime:
    """Return the next clock boundary that is a multiple of *interval_minutes*."""
    total_minutes = now.hour * 60 + now.minute
    minutes_into_slot = total_minutes % interval_minutes
    minutes_until_next = interval_minutes - minutes_into_slot
    next_time = (now + timedelta(minutes=minutes_until_next)).replace(
        second=0, microsecond=0
    )
    return next_time


def sleep_until(target: datetime) -> None:
    """Block until *target* (a timezone-aware or naive UTC datetime)."""
    now = datetime.now(tz=timezone.utc) if target.tzinfo else datetime.utcnow()
    delta = (target - now).total_seconds()
    if delta > 0:
        print(f"  Sleeping {delta:.0f}s until {target.strftime('%Y-%m-%d %H:%M:%S')} …")
        time.sleep(delta)


# ---------------------------------------------------------------------------
# Single-cycle run
# ---------------------------------------------------------------------------

def build_weather_by_date(args, start: str, end: str) -> dict[date, dict[str, Any]]:
    import pandas as pd

    start_date = pd.Timestamp(start).date()
    end_date = pd.Timestamp(end).date()

    if args.weather == "auto":
        return fetch_weather_by_date(
            start_date=start_date,
            end_date=end_date,
            latitude=args.latitude,
            longitude=args.longitude,
            timezone=args.timezone,
            rain_threshold_pct=args.rain_threshold_pct,
        )
    else:
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        return {
            day.date(): {
                "source": "manual",
                "weather_code": None,
                "rain_chance_pct": None,
                "precipitation_mm": None,
                "weather_switch": args.weather,
            }
            for day in dates
        }


def run_cycle(args, start: str, end: str) -> None:
    """Generate predictions for [start, end], write CSV + DB."""
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC] Generating {start} → {end}")

    weather_by_date = build_weather_by_date(args, start, end)
    predictions = generate_weather_adjusted_predictions(
        args.fourier,
        start,
        end,
        weather_by_date,
        args.sunny_boost,
        args.rainy_penalty,
    )

    # Always write CSV
    predictions.to_csv(args.output, index=False)
    weather_counts = predictions["WeatherSwitch"].value_counts().to_dict()
    print(f"  Weather switches : {weather_counts}")
    print(f"  Wrote {len(predictions)} rows → '{args.output}'")

    # Write to PostgreSQL unless --no-db was passed
    if not args.no_db:
        try:
            n = write_to_postgres(predictions)
            print(f"  Upserted {n} rows → {DB_TABLE} @ {DB_HOST}:{DB_PORT}/{DB_NAME}")
        except Exception as exc:
            print(f"  [WARNING] DB write failed: {exc}")
            print(f"  (CSV was still saved successfully)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Fourier traffic predictions with a sunny/rainy/neutral weather adjustment. "
            "Output goes to a CSV file and (optionally) a PostgreSQL table."
        )
    )
    parser.add_argument("-f", "--fourier", required=True, help="Path to input .npz Fourier archive")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument(
        "--weather",
        choices=["auto", "sunny", "rainy", "neutral"],
        default="auto",
        help="'auto' fetches Open-Meteo; the other values force a fixed state.",
    )
    parser.add_argument("--latitude",  type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
    parser.add_argument("--timezone",  default=DEFAULT_TIMEZONE)
    parser.add_argument("--rain-threshold-pct", type=int,   default=50)
    parser.add_argument("--sunny-boost",         type=float, default=0.08)
    parser.add_argument("--rainy-penalty",        type=float, default=0.20)
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip the PostgreSQL write (CSV only). Useful for local testing.",
    )

    # One-shot mode arguments (mutually exclusive with --continuous)
    oneshot = parser.add_argument_group("one-shot mode (default)")
    oneshot.add_argument("-S", "--start", help="Prediction start timestamp")
    oneshot.add_argument("-E", "--end",   help="Prediction end timestamp")

    # Continuous mode
    cont = parser.add_argument_group("continuous mode")
    cont.add_argument(
        "--continuous",
        action="store_true",
        help=(
            "Run forever, generating a new batch every OUTPUT_FREQUENCY_MINUTES minutes. "
            "The window starts at -S/--start and the end advances to the current "
            "interval boundary on each cycle. Requires -S/--start."
        ),
    )

    args = parser.parse_args()

    if args.continuous:
        # ----------------------------------------------------------------
        # Continuous mode: run immediately, then sleep to the next boundary.
        # Start is fixed at -S; end advances to the current interval boundary
        # on every cycle.
        # ----------------------------------------------------------------
        if not args.start:
            parser.error("Continuous mode requires -S/--start.")

        print(
            f"Continuous mode enabled. "
            f"Interval: {OUTPUT_FREQUENCY_MINUTES} min | "
            f"Fixed start: {args.start}"
        )
        while True:
            now = datetime.utcnow()
            # Snap 'end' back to the most-recently completed interval boundary
            minutes_into_slot = (now.hour * 60 + now.minute) % OUTPUT_FREQUENCY_MINUTES
            end_dt = (now - timedelta(minutes=minutes_into_slot)).replace(
                second=0, microsecond=0
            )

            run_cycle(args, args.start, end_dt.isoformat())

            # Sleep until the START of the next interval
            next_run = next_interval_start(datetime.utcnow(), OUTPUT_FREQUENCY_MINUTES)
            sleep_until(next_run)

    else:
        # ----------------------------------------------------------------
        # One-shot mode
        # ----------------------------------------------------------------
        if not args.start or not args.end:
            parser.error("One-shot mode requires -S/--start and -E/--end.")
        run_cycle(args, args.start, args.end)


if __name__ == "__main__":
    main()
