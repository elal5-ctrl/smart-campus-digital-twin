"""
generate_traffic.py — Anchor generation + PCHIP interpolation → output CSV.

Usage:
    # Run a localized one-shot simulation window
    python generate_traffic.py -f fourier_models.npz -S 2026-05-15 -E 2026-05-30T22:00:00 -o target_output.csv

    # Start the continuous live data generator engine
    python generate_traffic.py -f fourier_models.npz -S 2026-05-15 -C -o target_output.csv
"""

from __future__ import annotations

import argparse
import signal
import time
import threading
from typing import TYPE_CHECKING, Optional, Tuple, Dict, List, Any
# ── Optional weather-adjustment integration sketch ────────────────────────────
# from weather_adjusted_traffic import fetch_weather_by_date, weather_multiplier

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

# ── Configuration Constants ──────────────────────────────────────────────────
INTERPOLATION_FREQUENCY_MINUTES: int = 15   # Final output timeline sequence resolution
EXTRAPOLATION_SPARSE_HOURS: int = 2        # Separation steps for synthetic Fourier prediction anchors
LOOKAHEAD_HOURS: int = 1                    # Operational window added beyond runtime clock in live stream mode
STREAM_REFRESH_INTERVAL_SECONDS: int = 30  # Writing interval to updates file in continuous live streaming
TIMEZONE_NAME: str = "Asia/Tokyo"


def load_fourier_archive(
    npz_file_path: str,
) -> Tuple[
    Dict[int, Tuple[np.ndarray, int]],
    Dict[int, float],
    Dict[int, float],
    Dict[int, float],
    pd.DataFrame,
]:
    """
    Unpacks and extracts structural arrays from the target archive container to
    generate fast synthetic timelines without spatial file dependencies.
    """
    import numpy as np
    import pandas as pd

    archive = np.load(npz_file_path, allow_pickle=True)

    fourier_models: Dict[int, Tuple[np.ndarray, int]] = {}
    node_latitudes: Dict[int, float] = {}
    node_longitudes: Dict[int, float] = {}
    count_caps: Dict[int, float] = {}

    node_ids: set[int] = {
        int(key[len("coeffs_"):])
        for key in archive.files
        if key.startswith("coeffs_")
    }

    location_only_ids: set[int] = {
        int(key[len("latitude_"):])
        for key in archive.files
        if key.startswith("latitude_")
    } - node_ids

    for nid in node_ids:
        fourier_models[nid] = (
            archive[f"coeffs_{nid}"],
            int(archive[f"harmonics_{nid}"]),
        )
        node_latitudes[nid] = float(archive[f"latitude_{nid}"])
        node_longitudes[nid] = float(archive[f"longitude_{nid}"])
        count_caps[nid] = float(archive[f"count_cap_{nid}"])

    for nid in location_only_ids:
        node_latitudes[nid] = float(archive[f"latitude_{nid}"])
        node_longitudes[nid] = float(archive[f"longitude_{nid}"])

    snapped_df = pd.DataFrame({
        "node_id": archive["snapped_node_ids"].astype(int),
        "Timestamp": pd.to_datetime(archive["snapped_timestamps"]),
        "Count": archive["snapped_counts"].astype(int),
        "Latitude": archive["snapped_latitudes"].astype(float),
        "Longitude": archive["snapped_longitudes"].astype(float),
    })

    print(
        f"Loaded {len(fourier_models)} Fourier model profiles and "
        f"{len(snapped_df)} raw base measurements from '{npz_file_path}'."
    )
    return fourier_models, node_latitudes, node_longitudes, count_caps, snapped_df


def build_fourier_features(
    time_in_hours: np.ndarray,
    harmonic_count: int,
    period_hours: float = 24.0,
) -> np.ndarray:
    """
    Constructs a design matrix of cyclical Fourier basis features.
    """
    import numpy as np

    feature_columns: List[np.ndarray] = [np.ones(len(time_in_hours))]
    for harmonic_index in range(1, harmonic_count + 1):
        angular_frequency = 2 * np.pi * harmonic_index * time_in_hours / period_hours
        feature_columns.append(np.sin(angular_frequency))
        feature_columns.append(np.cos(angular_frequency))
    return np.column_stack(feature_columns)


def predict_fourier_profile(
    model: Tuple[np.ndarray, int],
    timestamps: List[pd.Timestamp],
    count_cap: float,
) -> np.ndarray:
    """
    Evaluates the Fourier regressions at designated timestamps and clips the output to [0, count_cap].
    """
    import numpy as np

    coefficients, actual_harmonics = model
    hour_of_day = np.array([ts.hour + ts.minute / 60.0 for ts in timestamps])
    design_matrix = build_fourier_features(hour_of_day, actual_harmonics)
    return np.clip(design_matrix @ coefficients, 0, count_cap)


def pchip_dense_interpolation(
    timestamps_known: List[pd.Timestamp],
    counts_known: List[float],
    frequency_minutes: int,
    end_datetime: Optional[pd.Timestamp] = None,
) -> List[Tuple[pd.Timestamp, int]]:
    """
    Applies Piecewise Cubic Hermite Interpolating Polynomial (PCHIP) to construct a
    smooth, overshoot-protected curve based on daily composite anchor coordinates.
    """
    import numpy as np
    import pandas as pd
    from scipy.interpolate import PchipInterpolator

    reference_time = min(timestamps_known)
    elapsed_seconds = np.array([(ts - reference_time).total_seconds() for ts in timestamps_known])
    target_counts = np.array(counts_known, dtype=float)

    pchip_interpolator = PchipInterpolator(elapsed_seconds, target_counts)

    time_grid_seconds = np.arange(elapsed_seconds.min(), elapsed_seconds.max() + 1, frequency_minutes * 60)
    interpolated_times = [reference_time + pd.Timedelta(seconds=float(sec)) for sec in time_grid_seconds]
    interpolated_counts = np.clip(pchip_interpolator(time_grid_seconds), 0, None).round().astype(int)

    return [
        (ts, int(cnt))
        for ts, cnt in zip(interpolated_times, interpolated_counts)
        if end_datetime is None or ts <= end_datetime
    ]


def process_node_pipeline(
    node_id: int,
    node_df: pd.DataFrame,
    end_datetime: pd.Timestamp,
    node_latitudes: Dict[int, float],
    node_longitudes: Dict[int, float],
    fourier_models: Dict[int, Tuple[np.ndarray, int]],
    count_caps: Dict[int, float],
    start_datetime: pd.Timestamp,
    # weather_by_date: Dict[object, Dict[str, object]],
) -> pd.DataFrame:
    """
    Processes single node outputs day-by-day, stitching actual sensor entries
    with boundary Fourier anchors before executing PCHIP generation sweeps.
    """
    import pandas as pd

    node_df = node_df.sort_values("Timestamp").reset_index(drop=True)
    latitude = node_latitudes[node_id]
    longitude = node_longitudes[node_id]
    generated_rows: List[Dict[str, Any]] = []

    if node_id not in fourier_models:
        print(f"  Node {node_id}: no profile profile models found; skipping configuration.")
        return pd.DataFrame(generated_rows)

    fourier_model = fourier_models[node_id]
    count_cap = count_caps[node_id]

    start_day_normalized = start_datetime.normalize()
    end_day_normalized = pd.Timestamp(end_datetime).normalize()
    date_range = pd.date_range(start_day_normalized, end_day_normalized, freq="D")

    for day in date_range:
        if day < start_day_normalized:
            continue

        day_cutoff = min(day + pd.Timedelta(hours=23, minutes=59), pd.Timestamp(end_datetime))

        # 1. Isolate actual observations within the daily window
        day_observations = node_df[node_df["Timestamp"].dt.normalize() == day]
        day_observations = day_observations.groupby("Timestamp", as_index=False)["Count"].sum()

        observed_times: List[pd.Timestamp] = day_observations["Timestamp"].tolist()
        observed_counts: List[float] = day_observations["Count"].tolist()

        # 2. Extract sparse Fourier anchors to bound open regions
        anchor_times_range = pd.date_range(
            day + pd.Timedelta(hours=6),
            day + pd.Timedelta(hours=22),
            freq=f"{EXTRAPOLATION_SPARSE_HOURS}h",
        )
        anchor_times: List[pd.Timestamp] = [t for t in anchor_times_range if t <= day_cutoff]
        anchor_counts = (
            predict_fourier_profile(fourier_model, anchor_times, count_cap)
            if anchor_times
            else []
        )

        anchor_timestamp_set = set(anchor_times)

        # 3. Stitch true indicators with safe outer boundary components
        final_anchor_times: List[pd.Timestamp] = list(observed_times)
        final_anchor_counts: List[float] = list(observed_counts)

        if observed_times:
            observed_min = min(observed_times)
            observed_max = max(observed_times)
            for anchor_t, anchor_c in zip(anchor_times, anchor_counts):
                # Only insert anchors if they fall outside the active data tracking domain
                if (
                    anchor_t < (observed_min - pd.Timedelta(minutes=30))
                    or anchor_t > (observed_max + pd.Timedelta(minutes=30))
                ):
                    final_anchor_times.append(anchor_t)
                    final_anchor_counts.append(float(anchor_c))
        else:
            final_anchor_times.extend(anchor_times)
            final_anchor_counts.extend([float(c) for c in anchor_counts])

        if len(final_anchor_times) < 2:
            continue

        # Chronological layout step required by PCHIP
        sorted_anchors = sorted(zip(final_anchor_times, final_anchor_counts), key=lambda x: x[0])
        chronological_times = [item[0] for item in sorted_anchors]
        chronological_counts = [item[1] for item in sorted_anchors]

        # 4. Generate high-density tracking timelines
        dense_pairs = pchip_dense_interpolation(
            chronological_times, chronological_counts, INTERPOLATION_FREQUENCY_MINUTES, end_datetime
        )

        # 5. Label analytical categorization source values
        observed_min_ts = min(observed_times) if observed_times else None
        observed_max_ts = max(observed_times) if observed_times else None

        for target_time, predicted_count in dense_pairs:
            if observed_min_ts is not None and observed_min_ts <= target_time <= observed_max_ts:
                data_source_label = "interpolated"
            elif target_time in anchor_timestamp_set:
                data_source_label = "extrapolated"
            else:
                data_source_label = "interpolated from anchors"

            # ── Optional weather adjustment sketch ───────────────────────────
            # weather_info = weather_by_date.get(
            #     target_time.date(),
            #     {"weather_switch": "neutral", "rain_chance_pct": None},
            # )
            # weather_switch = weather_info["weather_switch"]
            # weather_factor = weather_multiplier(weather_switch)
            # fourier_count = predicted_count
            # predicted_count = int(round(predicted_count * weather_factor))
            #
            # If enabled, the row below could also include:
            #     "FourierCount": fourier_count,
            #     "WeatherSwitch": weather_switch,
            #     "RainChancePct": weather_info["rain_chance_pct"],
            #     "WeatherMultiplier": weather_factor,

            generated_rows.append({
                "node_id": node_id,
                "Timestamp": target_time,
                "Latitude": latitude,
                "Longitude": longitude,
                "Count": predicted_count,
                "Source": data_source_label,
            })

    return pd.DataFrame(generated_rows)


def finalise_output_dataframe(dataframe_segments: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Merges separate processing blocks, creates clean chronological indexes,
    and applies layout schemas formatting to matches output targets.
    """
    import pandas as pd

    if not dataframe_segments:
        return None
        
    compiled_df = pd.concat(dataframe_segments, ignore_index=True)
    compiled_df = compiled_df.sort_values(["node_id", "Timestamp"]).reset_index(drop=True)
    
    # Inject primary key formatting sequentially starting at index 1
    compiled_df.insert(0, "Primary key", range(1, len(compiled_df) + 1))
    compiled_df["Timestamp"] = compiled_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    return compiled_df[
        ["Primary key", "node_id", "Timestamp", "Latitude", "Longitude", "Count", "Source"]
    ]


def run_oneshot_mode(
    snapped_df: pd.DataFrame,
    fourier_models: Dict[int, Tuple[np.ndarray, int]],
    node_latitudes: Dict[int, float],
    node_longitudes: Dict[int, float],
    count_caps: Dict[int, float],
    start_datetime: pd.Timestamp,
    end_datetime: pd.Timestamp,
    output_file_path: str,
    # weather_by_date: Dict[object, Dict[str, object]],
) -> None:
    """Executes a single structural simulation sweep over bounded static parameters."""
    dataframe_segments: List[pd.DataFrame] = []
    
    for node_id, node_group_df in snapped_df.groupby("node_id"):
        print(f"  Evaluating node {node_id} containing {len(node_group_df)} observations...")
        segment = process_node_pipeline(
            int(node_id), node_group_df, end_datetime,
            node_latitudes, node_longitudes, fourier_models, count_caps, start_datetime,
            # weather_by_date,
        )
        if not segment.empty:
            dataframe_segments.append(segment)

    finalized_df = finalise_output_dataframe(dataframe_segments)
    if finalized_df is None:
        print("Simulation yielded no active entries.")
        return

    finalized_df.to_csv(output_file_path, index=False)
    print(f"\nSimulation complete. {len(finalized_df)} steps recorded safely -> '{output_file_path}'.")
    print(finalized_df.groupby(["node_id", "Source"])["Primary key"].count().to_string())


def run_continuous_mode(
    snapped_df: pd.DataFrame,
    fourier_models: Dict[int, Tuple[np.ndarray, int]],
    node_latitudes: Dict[int, float],
    node_longitudes: Dict[int, float],
    count_caps: Dict[int, float],
    start_datetime: pd.Timestamp,
    output_file_path: str,
    # weather_by_date: Dict[object, Dict[str, object]],
) -> None:
    """Executes an uninterrupted processing loop regularizing live database drops."""
    execution_stop_event = threading.Event()

    def terminate_signal_handler(signal_number: int, frame_object: object) -> None:
        print("\nTermination intercept triggered. Halting simulation loops...")
        execution_stop_event.set()

    signal.signal(signal.SIGINT, terminate_signal_handler)
    signal.signal(signal.SIGTERM, terminate_signal_handler)

    print(f"Continuous engine active. File dumps occurring every {STREAM_REFRESH_INTERVAL_SECONDS}s. Press Ctrl+C to terminate.")

    while not execution_stop_event.is_set():
        import pandas as pd

        current_system_time = pd.Timestamp.now()
        dynamic_end_datetime = current_system_time + pd.Timedelta(hours=LOOKAHEAD_HOURS)

        dataframe_segments: List[pd.DataFrame] = []
        for node_id, node_group_df in snapped_df.groupby("node_id"):
            segment = process_node_pipeline(
                int(node_id), node_group_df, dynamic_end_datetime,
                node_latitudes, node_longitudes, fourier_models, count_caps, start_datetime,
                # weather_by_date,
            )
            if not segment.empty:
                dataframe_segments.append(segment)

        finalized_df = finalise_output_dataframe(dataframe_segments)
        if finalized_df is not None:
            finalized_df.to_csv(output_file_path, index=False)
            print(f"[{current_system_time.strftime('%H:%M:%S')}] Logged {len(finalized_df)} simulation rows into '{output_file_path}'.")

        # Fragmented polling step maintains thread interaction safety
        for _ in range(STREAM_REFRESH_INTERVAL_SECONDS * 10):
            if execution_stop_event.is_set():
                break
            time.sleep(0.1)

    print("Pipeline engine suspended cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generates continuous high-density campus pedestrian flow metrics tracking structural models."
    )
    parser.add_argument("-f", "--fourier", required=True, help="Path to input precomputed .npz archive file")
    parser.add_argument("-S", "--start", required=True, help="Simulation start timestamp (e.g., '2026-05-15')")
    parser.add_argument("-E", "--end", default=None, help="Simulation end timestamp (One-shot mode only)")
    parser.add_argument("-C", "--continuous", action="store_true", help="Activates automated real-time streaming engine updates")
    parser.add_argument("-o", "--output", required=True, help="Path to output simulation CSV result file")
    # parser.add_argument("--weather", choices=["auto", "sunny", "rainy", "neutral"], default="auto")
    # parser.add_argument("--weather-latitude", type=float, default=34.8102)
    # parser.add_argument("--weather-longitude", type=float, default=135.5616)
    # parser.add_argument("--rain-threshold-pct", type=int, default=50)
    args = parser.parse_args()

    import pandas as pd

    is_continuous_mode = bool(args.continuous)
    if is_continuous_mode and args.end:
        print("Note: Continuous generator active (-C). Static date boundary constraints (-E) will be ignored.")

    fourier_models, node_latitudes, node_longitudes, count_caps, snapped_df = load_fourier_archive(args.fourier)
    start_datetime = pd.Timestamp(args.start)

    if is_continuous_mode:
        # weather_by_date = fetch_weather_by_date(
        #     start_date=start_datetime.date(),
        #     end_date=(pd.Timestamp.now() + pd.Timedelta(hours=LOOKAHEAD_HOURS)).date(),
        #     latitude=args.weather_latitude,
        #     longitude=args.weather_longitude,
        #     rain_threshold_pct=args.rain_threshold_pct,
        # )
        # if args.weather != "auto":
        #     weather_by_date = {
        #         day.date(): {
        #             "source": "manual",
        #             "weather_switch": args.weather,
        #             "rain_chance_pct": None,
        #             "precipitation_mm": None,
        #         }
        #         for day in pd.date_range(
        #             start=start_datetime.date(),
        #             end=(pd.Timestamp.now() + pd.Timedelta(hours=LOOKAHEAD_HOURS)).date(),
        #             freq="D",
        #         )
        #     }
        run_continuous_mode(
            snapped_df, fourier_models, node_latitudes, node_longitudes, count_caps,
            start_datetime, args.output
            # , weather_by_date
        )
    else:
        if args.end is None:
            parser.error("Parameter Error: One-shot mode sweeps require a designated end target execution date constraint (-E).")
        end_datetime = pd.Timestamp(args.end)
        # weather_by_date = fetch_weather_by_date(
        #     start_date=start_datetime.date(),
        #     end_date=end_datetime.date(),
        #     latitude=args.weather_latitude,
        #     longitude=args.weather_longitude,
        #     rain_threshold_pct=args.rain_threshold_pct,
        # )
        # if args.weather != "auto":
        #     weather_by_date = {
        #         day.date(): {
        #             "source": "manual",
        #             "weather_switch": args.weather,
        #             "rain_chance_pct": None,
        #             "precipitation_mm": None,
        #         }
        #         for day in pd.date_range(
        #             start=start_datetime.date(),
        #             end=end_datetime.date(),
        #             freq="D",
        #         )
        #     }
        print(f"Initializing fixed structural execution sweep: {start_datetime} to {end_datetime}")
        run_oneshot_mode(
            snapped_df, fourier_models, node_latitudes, node_longitudes, count_caps,
            start_datetime, end_datetime, args.output
            # , weather_by_date
        )


if __name__ == "__main__":
    main()
