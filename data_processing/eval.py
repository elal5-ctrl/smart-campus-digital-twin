"""
eval.py — Leave-One-Day-Out Cross-Validation for Fourier Traffic Models.

Usage:
    python eval.py
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import List, Tuple

# ── Configuration Constants ──────────────────────────────────────────────────
INPUT_CSV_PATH: str = "data3.csv"
HARMONIC_COUNT: int = 24  # Harmonic count used for validation mapping profiles


def build_fourier_features(
    time_in_hours: np.ndarray,
    harmonic_count: int = HARMONIC_COUNT,
    period_hours: float = 24.0,
) -> np.ndarray:
    """
    Constructs a design matrix of cyclical Fourier components for validation routines.
    """
    feature_columns: List[np.ndarray] = [np.ones(len(time_in_hours))]
    for harmonic_index in range(1, harmonic_count + 1):
        angular_frequency = 2 * np.pi * harmonic_index * time_in_hours / period_hours
        feature_columns.append(np.sin(angular_frequency))
        feature_columns.append(np.cos(angular_frequency))
    return np.column_stack(feature_columns)


def main() -> None:
    print(f"Loading target dataset from source file '{INPUT_CSV_PATH}'...")
    traffic_df = pd.read_csv(INPUT_CSV_PATH, skipinitialspace=True)

    # Parse inputs cleanly into structured temporal dates
    traffic_df["Timestamp"] = pd.to_datetime(traffic_df["Timestamp"])

    # Eliminate weekend fluctuations from accuracy testing pools (Sat = 5, Sun = 6)
    weekday_traffic_df = traffic_df[traffic_df["Timestamp"].dt.dayofweek < 5].copy()
    weekday_traffic_df["Date"] = weekday_traffic_df["Timestamp"].dt.date

    # Combine observations globally across campus sensor arrays to isolate macroscopic trends
    aggregated_daily_df = weekday_traffic_df.groupby(["Date", "Timestamp"], as_index=False)["Count"].sum()

    overall_mean_count = aggregated_daily_df["Count"].mean()
    unique_test_days = aggregated_daily_df["Date"].unique()

    print(f"Found {len(unique_test_days)} individual weekdays available for model cross-validation.")
    print(f"Baseline overall mean traffic count: {overall_mean_count:.2f} entries\n")

    mean_absolute_errors: List[float] = []
    
    # Validation performance visualization table header
    print(f"{'Evaluation Date':25} | {'MAE':<12} | {'Relative Error':<15}")
    print("-" * 60)

    for test_day in unique_test_days:
        # Split target data subsets into training segments and a lone left-out day
        training_set = aggregated_daily_df[aggregated_daily_df["Date"] != test_day]
        testing_set = aggregated_daily_df[aggregated_daily_df["Date"] == test_day]

        if len(training_set) < 3 or testing_set.empty:
            continue

        # ── Profile Training Optimization Sweep ──
        hours_train = (
            training_set["Timestamp"].dt.hour + training_set["Timestamp"].dt.minute / 60.0
        ).to_numpy()
        counts_train = training_set["Count"].to_numpy().astype(float)

        design_matrix_train = build_fourier_features(hours_train, HARMONIC_COUNT)
        coefficients, _, _, _ = np.linalg.lstsq(design_matrix_train, counts_train, rcond=None)

        # ── Prediction Estimation Evaluation ──
        hours_test = (
            testing_set["Timestamp"].dt.hour + testing_set["Timestamp"].dt.minute / 60.0
        ).to_numpy()
        counts_true = testing_set["Count"].to_numpy().astype(float)

        design_matrix_test = build_fourier_features(hours_test, HARMONIC_COUNT)
        counts_predicted = np.clip(design_matrix_test @ coefficients, 0, None)

        # ── Error Metrics Generation ──
        mae = float(np.mean(np.abs(counts_true - counts_predicted)))
        mean_absolute_errors.append(mae)

        relative_error_percentage = (mae / overall_mean_count) * 100
        day_of_week_name = pd.Timestamp(test_day).day_name()
        
        print(f"{str(test_day)} ({day_of_week_name:9}) | {mae:6.2f} counts | {relative_error_percentage:6.2f}%")

    # ── Compiled Performance Report ──
    if mean_absolute_errors:
        final_cross_val_mae = float(np.mean(mean_absolute_errors))
        final_overall_relative_error = (final_cross_val_mae / overall_mean_count) * 100
        print(f"\n==========================================")
        print(f"Leave-One-Day-Out MAE:   {final_cross_val_mae:.2f} counts")
        print(f"Overall Relative Error:  {final_overall_relative_error:.2f}%")
        print(f"==========================================")


if __name__ == "__main__":
    main()
