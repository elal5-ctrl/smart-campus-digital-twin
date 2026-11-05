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

Examples:
    python weather_adjusted_traffic.py -f weights.npz -S 2026-05-15 -E 2026-05-15T22:00:00 -o weather_output.csv
    python weather_adjusted_traffic.py -f weights.npz -S 2026-05-15 -E 2026-05-15T22:00:00 --weather rainy -o weather_output.csv
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from urllib.request import urlopen

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


OUTPUT_FREQUENCY_MINUTES = 15
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_LATITUDE = 34.8102
DEFAULT_LONGITUDE = 135.5616
DEFAULT_TIMEZONE = "Asia/Tokyo"

SUNNY_WEATHER_CODES = {0, 1}
RAINY_WEATHER_CODES = {
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    80,
    81,
    82,
    95,
    96,
    99,
}


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

        weather_switch = classify_weather(
            weather_code,
            rain_chance_pct,
            rain_threshold_pct,
        )
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


def load_fourier_archive(
    npz_file_path: str,
) -> tuple[dict[int, tuple[np.ndarray, int]], dict[int, float], dict[int, float], dict[int, float]]:
    import numpy as np

    archive = np.load(npz_file_path, allow_pickle=True)
    node_ids = sorted(
        int(key[len("coeffs_") :])
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
    timestamps = pd.date_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq=f"{OUTPUT_FREQUENCY_MINUTES}min")

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Fourier traffic predictions with a simple sunny/rainy/neutral weather adjustment."
    )
    parser.add_argument("-f", "--fourier", required=True, help="Path to input .npz Fourier archive")
    parser.add_argument("-S", "--start", required=True, help="Prediction start timestamp")
    parser.add_argument("-E", "--end", required=True, help="Prediction end timestamp")
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument(
        "--weather",
        choices=["auto", "sunny", "rainy", "neutral"],
        default="auto",
        help="Use 'auto' to fetch Open-Meteo by date, or force one switch state.",
    )
    parser.add_argument("--latitude", type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--rain-threshold-pct", type=int, default=50)
    parser.add_argument("--sunny-boost", type=float, default=0.08)
    parser.add_argument("--rainy-penalty", type=float, default=0.20)
    args = parser.parse_args()

    if args.weather == "auto":
        import pandas as pd

        start_date = pd.Timestamp(args.start).date()
        end_date = pd.Timestamp(args.end).date()
        weather_by_date = fetch_weather_by_date(
            start_date=start_date,
            end_date=end_date,
            latitude=args.latitude,
            longitude=args.longitude,
            timezone=args.timezone,
            rain_threshold_pct=args.rain_threshold_pct,
        )
    else:
        import pandas as pd

        start_date = pd.Timestamp(args.start).date()
        end_date = pd.Timestamp(args.end).date()
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        weather_by_date = {
            day.date(): {
                "source": "manual",
                "weather_code": None,
                "rain_chance_pct": None,
                "precipitation_mm": None,
                "weather_switch": args.weather,
            }
            for day in dates
        }

    predictions = generate_weather_adjusted_predictions(
        args.fourier,
        args.start,
        args.end,
        weather_by_date,
        args.sunny_boost,
        args.rainy_penalty,
    )
    predictions.to_csv(args.output, index=False)

    weather_counts = predictions["WeatherSwitch"].value_counts().to_dict()
    print(f"Weather switches: {weather_counts}")
    print(f"Wrote {len(predictions)} rows to '{args.output}'")


if __name__ == "__main__":
    main()
