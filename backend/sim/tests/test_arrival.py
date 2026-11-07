import json

import pytest

from backend.sim.engine.arrival import ArrivalGrid
from backend.sim.engine.run import run_engine

# West Edmonton ignition, clear west wind (spreads east), 2 h horizon.
LAT, LON = 53.535, -113.663
D = 0.002


@pytest.fixture(scope="module")
def grid(tmp_path_factory):
    scenario = {
        "schema": "v1",
        "scenario_id": "arrival-test",
        "run_id": "arrival-test",
        "t0": "2026-11-08T20:00:00Z",
        "horizon_min": 120,
        "step_min": 15,
        "bbox": [-113.70, 53.42, -113.43, 53.58],
        "initial_perimeter": {
            "type": "Polygon",
            "coordinates": [[[LON - D, LAT - D], [LON + D, LAT - D], [LON + D, LAT + D], [LON - D, LAT + D], [LON - D, LAT - D]]],
        },
        "weather": [{"t_min": 0, "wind_speed_ms": 7, "wind_dir_deg": 270, "temp_c": 20, "rh_pct": 20, "precip_mm": 0}],
        "n_ensemble": 1,
    }
    out = tmp_path_factory.mktemp("runs")
    return ArrivalGrid.load(run_engine(json.dumps(scenario), out)["out_dir"])


def test_ignition_burns_at_zero(grid):
    assert grid.arrival_min(LAT, LON) == 0


def test_downwind_earlier_than_upwind(grid):
    # 1 km east (downwind) vs 1 km west (upwind) of the ignition.
    dlon = 1000 / (111320 * 0.5951)
    downwind = grid.arrival_min(LAT, LON + dlon)
    upwind = grid.arrival_min(LAT, LON - dlon)
    assert downwind is not None
    assert upwind is None or downwind < upwind


def test_beyond_horizon_or_grid_is_none(grid):
    assert grid.arrival_min(53.43, -113.69) is None  # far upwind corner, inside bbox
    assert grid.arrival_min(53.0, -113.0) is None    # outside the grid
