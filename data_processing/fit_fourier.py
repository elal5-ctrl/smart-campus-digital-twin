"""
fit_fourier.py — Load graph, snap sensors, fit Fourier models, write .npz.

================================================================================
Usage:
    python fit_fourier.py -i data.csv -o fourier_coeffs.npz

Flags:
    -i  Input sensor CSV  (required)
    -o  Output .npz file  (required)

What is stored in the .npz archive
------------------------------------
Per fitted node_id:
    coeffs_<node_id>      float64 array  — Fourier coefficients
    harmonics_<node_id>   int scalar     — actual harmonic count used
    coord_<node_id>       str scalar     — "POINT(lon lat)" for that node
    latitude_<node_id>    float scalar   — latitude for that node
    longitude_<node_id>   float scalar   — longitude for that node
    count_cap_<node_id>   float scalar   — p99 of training counts for that node

Shared across all nodes:
    snapped_node_ids      int64 array    — node_id per input row (same order as CSV)
    snapped_timestamps    str array      — ISO timestamp per input row
    snapped_counts        int64 array    — COUNT [INT] per input row
    snapped_coords        str array      — "POINT(lon lat)" per input row (sensor coord)
    snapped_latitudes     float64 array  — numeric latitude per input row
    snapped_longitudes    float64 array  — numeric longitude per input row

Heavy libraries (numpy, pandas, osmnx, networkx, shapely) are imported lazily
inside each function so that `python fit_fourier.py -h` returns instantly.
"""

from __future__ import annotations

import argparse
import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import networkx as nx
    import numpy as np
    import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
POLYGON_FILE:         str   = "polygon.txt"
N_HARMONICS:          int   = 27
TIMEZONE:             str   = "Asia/Tokyo"
COUNT_CAP_PERCENTILE: float = 99.0   # p-ile of training data used as anchor ceiling


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH
# ─────────────────────────────────────────────────────────────────────────────
def load_graph(polygon_file: str) -> tuple[nx.Graph, dict[int, tuple[float, float]]]:
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import Polygon

    coords: list[tuple[float, float]] = []

    with open(polygon_file) as f:
        for line in f:
            line = line.strip()
            if line:
                lon, lat = ast.literal_eval(line)
                coords.append((lon, lat))

    if coords[0] != coords[-1]:
        coords.append(coords[0])

    graph = ox.graph_from_polygon(Polygon(coords), network_type="walk")
    graph = graph.to_undirected()

    lcc   = max(nx.connected_components(graph), key=len)
    graph = graph.subgraph(lcc).copy()
    nodes: dict[int, tuple[float, float]] = {
        nid: (d["y"], d["x"]) for nid, d in graph.nodes(data=True)
    }

    print(f"Graph loaded: {len(nodes)} nodes")
    return graph, nodes


# ─────────────────────────────────────────────────────────────────────────────
# SENSOR DATA
# ─────────────────────────────────────────────────────────────────────────────
def load_sensors(csv_file: str) -> pd.DataFrame:
    import pandas as pd

    df = pd.read_csv(csv_file, skipinitialspace=True)
    
    # Clean whitespace from column strings if any exist
    df.columns = df.columns.str.strip()

    s_time = pd.to_datetime(df["TIMESTAMPTZ"])
    if s_time.dt.tz is not None:
        df["TIMESTAMPTZ"] = s_time.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    else:
        df["TIMESTAMPTZ"] = s_time

    def parse_coord(geo: str) -> tuple[float, float]:
        geo = str(geo).replace("POINT(", "").replace(")", "").strip()
        lon_s, lat_s = geo.split()
        return float(lon_s), float(lat_s)

    df[["sensor_lon", "sensor_lat"]] = df["Koordinaten [GEOGRAPHY]"].apply(
        lambda g: pd.Series(parse_coord(g))
    )
    return df.sort_values("TIMESTAMPTZ").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# SNAP sensors → nearest graph node
# ─────────────────────────────────────────────────────────────────────────────
def snap_sensors_to_nodes(
    sensor_df: pd.DataFrame,
    nodes: dict[int, tuple[float, float]],
) -> pd.DataFrame:
    import numpy as np

    node_ids  = np.array(list(nodes.keys()))
    node_lats = np.array([nodes[n][0] for n in node_ids])
    node_lons = np.array([nodes[n][1] for n in node_ids])

    assigned: list[int] = []
    for _, row in sensor_df.iterrows():
        dist = (node_lats - row["sensor_lat"]) ** 2 + (node_lons - row["sensor_lon"]) ** 2
        assigned.append(int(node_ids[np.argmin(dist)]))

    sensor_df = sensor_df.copy()
    sensor_df["node_id"] = assigned
    print(f"Sensors snapped → {sensor_df['node_id'].nunique()} unique node(s)")
    return sensor_df


# ─────────────────────────────────────────────────────────────────────────────
# FOURIER MODEL
# ─────────────────────────────────────────────────────────────────────────────
def build_fourier_features(
    t_hours: np.ndarray,
    n_harmonics: int = N_HARMONICS,
    period: float = 24.0,
) -> np.ndarray:
    import numpy as np

    features: list[np.ndarray] = [np.ones(len(t_hours))]
    for k in range(1, n_harmonics + 1):
        features.append(np.sin(2 * np.pi * k * t_hours / period))
        features.append(np.cos(2 * np.pi * k * t_hours / period))
    return np.column_stack(features)

def fit_fourier_model(
    node_df: pd.DataFrame,
    n_harmonics: int = N_HARMONICS,
) -> tuple[np.ndarray, int]:
    """
    Fit on hour-of-day only.  Automatically reduces harmonics when there isn't
    enough data to prevent overfitting.
    Returns (coeffs, actual_harmonics_used).
    """
    import numpy as np

    max_possible:     int = max(0, (len(node_df) - 1) // 2)
    actual_harmonics: int = min(n_harmonics, max_possible)

    hod: np.ndarray = (
        node_df["TIMESTAMPTZ"].dt.hour + node_df["TIMESTAMPTZ"].dt.minute / 60.0
    ).to_numpy()
    y: np.ndarray = node_df["COUNT [INT]"].to_numpy().astype(float)
    X: np.ndarray = build_fourier_features(hod, n_harmonics)

    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    return coeffs, actual_harmonics


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Load walk graph, snap sensors to nodes, fit per-node Fourier models, "
            "and save everything needed by downstream tools into one .npz file."
        )
    )
    parser.add_argument("-i", "--input",  required=True, help="Input sensor CSV")
    parser.add_argument("-o", "--output", required=True, help="Output .npz file")
    args = parser.parse_args()

    # ── Heavy imports — only reached after -h / arg errors have already exited ──
    import numpy as np

    _G, nodes = load_graph(POLYGON_FILE)
    sensor_df = load_sensors(args.input)
    snapped   = snap_sensors_to_nodes(sensor_df, nodes)

    save_dict: dict[str, object] = {}

    # ── Shared arrays across all records (Fulfills generate_traffic & predict_traffic) ──
    save_dict["snapped_node_ids"]   = snapped["node_id"].to_numpy(dtype=np.int64)
    save_dict["snapped_timestamps"] = snapped["TIMESTAMPTZ"].dt.strftime(
        "%Y-%m-%dT%H:%M:%S"
    ).to_numpy()
    save_dict["snapped_counts"]     = snapped["COUNT [INT]"].to_numpy(dtype=np.int64)
    save_dict["snapped_coords"]     = snapped["Koordinaten [GEOGRAPHY]"].to_numpy()
    save_dict["snapped_latitudes"]  = snapped["sensor_lat"].to_numpy(dtype=float)
    save_dict["snapped_longitudes"] = snapped["sensor_lon"].to_numpy(dtype=float)

    # ── Only keep nodes that have actual measured data ───────────────────────────
    measured_node_ids = snapped["node_id"].unique()
    print(f"\nFitting models for {len(measured_node_ids)} node(s) with measured data "
          f"(discarding {len(nodes) - len(measured_node_ids)} unmeasured graph nodes)")

    # ── Fit one Fourier model per node that has measurements ─────────────────────
    for node_id, node_df in snapped.groupby("node_id"):
        lat, lon = nodes[int(node_id)]
        coord    = f"POINT({lon:.6f} {lat:.6f})"

        # Store coordinates in both WKT formats and explicit numerical formats 
        save_dict[f"coord_{node_id}"]     = np.array(coord)
        save_dict[f"latitude_{node_id}"]  = np.array(lat)
        save_dict[f"longitude_{node_id}"] = np.array(lon)

        fit_df = node_df.groupby("TIMESTAMPTZ", as_index=False)["COUNT [INT]"].sum()

        if len(fit_df) < 3:
            print(f"  Node {node_id}: too few points — coordinates saved, model skipped")
            continue

        coeffs, actual_harmonics = fit_fourier_model(fit_df)

        # p99 cap derived from this node's own training counts
        count_cap: float = float(
            np.percentile(fit_df["COUNT [INT]"].to_numpy(), COUNT_CAP_PERCENTILE)
        )

        save_dict[f"coeffs_{node_id}"]    = coeffs
        save_dict[f"harmonics_{node_id}"] = np.array(actual_harmonics)
        save_dict[f"count_cap_{node_id}"] = np.array(count_cap)

        print(
            f"  Node {node_id}: {len(fit_df)} readings, "
            f"{actual_harmonics} harmonics, cap={count_cap:.0f}"
        )

    np.savez(args.output, **save_dict)
    print(f"\nCoefficients + snapped data saved → '{args.output}'")


if __name__ == "__main__":
    main()
