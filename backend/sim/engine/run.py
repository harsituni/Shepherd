"""Run the spread engine: Contract A → runs/{run_id}/ (B1 + B2 + run_meta.json).

Usage (from the repo root):
    python -m backend.sim.engine.run backend/sim/contracts/scenario_a.example.json
    python -m backend.sim.engine.run scenario.json --out runs/ --mock --cell-m 100
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from backend.sim.engine import ensemble
from backend.sim.engine.contracts import (
    load_scenario,
    write_b1,
    write_frames,
    write_run_meta,
)
from backend.sim.engine.frames import perimeter_frames
from backend.sim.engine.grid import DEFAULT_CELL_M, build_grid, seed_mask, to_utm
from backend.sim.engine.mock import MOCK_HEAD_ROS_M_PER_MIN, MOCK_LB, mock_arrival
from backend.sim.engine.spread import compute_arrival
from backend.sim.engine.weather import build_weather_table, spread_bearing

ENGINE_VERSION = "0.1.0"

ASSUMPTIONS = [
    "Fuel is uniform over the whole grid (one FBP fuel type, M-1 by default).",
    "FFMC and BUI are fixed for the whole run (default 92 / 90, high fire danger). "
    "temp_c, rh_pct and precip_mm are read but do not change fuel moisture in v1.",
    "No day/night moisture cycle, so night spread is overpredicted (conservative).",
    "Slope is 0 everywhere; net effective wind speed = forecast 10 m wind speed.",
    "No acceleration: fire spreads at its equilibrium rate from t = 0 (conservative).",
    "Every cell is burnable (no water, roads or urban breaks in v1).",
    "Fire shape is the FBP ellipse with the ignition at the rear focus.",
    "Grid north = UTM 12N north; grid convergence (<= ~2 deg here) is ignored.",
    "Wind is interpolated linearly as vector components between forecast entries.",
    "Outputs are predictions from a simplified model, not certainties.",
]
MOCK_ASSUMPTIONS = [
    f"MOCK RUN: analytic ellipse, head rate {MOCK_HEAD_ROS_M_PER_MIN} m/min, LB {MOCK_LB}, "
    "t = 0 wind direction held for the whole run, no FBP.",
]


def run_engine(scenario, out_root: Path = Path("runs"), *, mock=False, cell_m=DEFAULT_CELL_M) -> dict:
    """Validate Contract A, simulate, write B1 + B2 to out_root/run_id/. Returns
    {"run_id", "out_dir", "b1_header_path", "frames_path", "elapsed_s"}."""
    started = time.perf_counter()
    sc = load_scenario(scenario)
    horizon = sc.horizon_min
    grid = build_grid(sc.bbox, cell_m)
    perimeter = to_utm(sc.initial_perimeter.to_shapely())
    seeds = seed_mask(perimeter, grid)
    burnable = np.ones(grid.shape, dtype=bool)

    if mock:
        members = []
        bearing = spread_bearing(sc.weather[0].wind_dir_deg)
        centroid = (perimeter.centroid.x, perimeter.centroid.y)
        arrivals = [mock_arrival(seeds, grid, centroid, bearing, horizon)]
    else:
        members = ensemble.make_members(sc.weather, sc.n_ensemble, sc.run_id)
        arrivals = [
            compute_arrival(seeds, burnable, build_weather_table(m.weather, sc.fbp, horizon), cell_m, horizon)
            for m in members
        ]
    p50, p10 = ensemble.combine(arrivals, horizon)
    spread_s = time.perf_counter() - started

    features = perimeter_frames(p50, grid, sc.bbox, horizon, sc.step_min, "p50")
    if len(arrivals) > 1:
        features += perimeter_frames(p10, grid, sc.bbox, horizon, sc.step_min, "p10")

    out_dir = Path(out_root) / sc.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    header_path = write_b1(out_dir, sc.run_id, grid, p50, p10)
    frames_path = write_frames(out_dir, sc.run_id, features)
    elapsed = time.perf_counter() - started

    write_run_meta(out_dir, {
        "schema": "v1",
        "run_id": sc.run_id,
        "scenario_id": sc.scenario_id,
        "t0": sc.t0.isoformat().replace("+00:00", "Z"),
        "engine_version": ENGINE_VERSION,
        "mode": "mock" if mock else "fbp",
        "cell_m": cell_m,
        "horizon_min": horizon,
        "step_min": sc.step_min,
        "fbp": sc.fbp.model_dump(),
        "fbp_from_scenario": "fbp" in sc.model_fields_set,
        "n_ensemble": len(arrivals),
        "members": [
            {"wind_factor": m.wind_factor, "dir_offset_deg": m.dir_offset_deg} for m in members
        ],
        "seed_cells": int(seeds.sum()),
        "cells_reached_p50": int(np.isfinite(p50).sum()),
        "assumptions": (MOCK_ASSUMPTIONS if mock else []) + ASSUMPTIONS,
        "timings_s": {"spread": round(spread_s, 3), "total": round(elapsed, 3)},
    })
    return {
        "run_id": sc.run_id,
        "out_dir": str(out_dir),
        "b1_header_path": str(header_path),
        "frames_path": str(frames_path),
        "elapsed_s": round(elapsed, 3),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Wildfire spread engine (Contract A → B1 + B2).")
    parser.add_argument("scenario", type=Path, help="Contract A scenario JSON")
    parser.add_argument("--out", type=Path, default=Path("runs"), help="output root (default runs/)")
    parser.add_argument("--mock", action="store_true", help="analytic ellipse instead of FBP")
    parser.add_argument("--cell-m", type=int, default=DEFAULT_CELL_M, help="grid cell size in metres")
    args = parser.parse_args(argv)
    print(json.dumps(run_engine(args.scenario, args.out, mock=args.mock, cell_m=args.cell_m), indent=2))


if __name__ == "__main__":
    main()
