import math

import numpy as np
import pytest

from backend.sim.engine.contracts import FbpParams, WeatherEntry
from backend.sim.engine.spread import NEIGHBOURS_16, compute_arrival, jumped_cells, neighbour_bearing
from backend.sim.engine.weather import build_weather_table

CELL_M = 10


def constant_table(speed_ms, wind_from, horizon):
    weather = [WeatherEntry(t_min=0, wind_speed_ms=speed_ms, wind_dir_deg=wind_from, temp_c=20, rh_pct=20, precip_mm=0)]
    return build_weather_table(weather, FbpParams(), horizon)


def point_fire(rows, cols, r0, c0, table, horizon, burnable=None):
    seed = np.zeros((rows, cols), dtype=bool)
    seed[r0, c0] = True
    if burnable is None:
        burnable = np.ones((rows, cols), dtype=bool)
    return compute_arrival(seed, burnable, table, CELL_M, horizon)


def test_stencil_bearings():
    assert len(set(NEIGHBOURS_16)) == 16
    assert neighbour_bearing(-1, 0) == 0     # north
    assert neighbour_bearing(0, 1) == 90     # east
    assert neighbour_bearing(1, 0) == 180    # south
    assert neighbour_bearing(0, -1) == 270   # west
    assert set(jumped_cells(1, 2)) == {(0, 1), (1, 1)}
    assert set(jumped_cells(-2, -1)) == {(-1, 0), (-1, -1)}


def test_constant_wind_ellipse_downwind():
    horizon = 60
    table = constant_table(7, 270, horizon)  # from the west → spreads east
    ros, bros = table.ros[0], table.bros[0]
    r0, c0 = 60, 20
    arrival = point_fire(120, 160, r0, c0, table, horizon)

    # Straight-line arrivals along the axis follow head and back rates exactly.
    for k in (1, 5, 10):
        assert arrival[r0, c0 + k] == pytest.approx(k * CELL_M / ros, rel=1e-5)
    assert arrival[r0, c0 - 3] == pytest.approx(3 * CELL_M / bros, rel=1e-5)
    assert arrival[r0, c0 - 3] / arrival[r0, c0 + 3] == pytest.approx(ros / bros, rel=1e-5)

    burned = np.isfinite(arrival)
    rr, cc = np.nonzero(burned)
    east, west = cc.max() - c0, c0 - cc.min()
    half_width = max(r0 - rr.min(), rr.max() - r0)
    assert east > half_width > west


def test_calm_is_roughly_circular():
    horizon = 30
    table = constant_table(0, 0, horizon)
    arrival = point_fire(101, 101, 50, 50, table, horizon)
    rr, cc = np.nonzero(np.isfinite(arrival))
    extents = [50 - rr.min(), rr.max() - 50, 50 - cc.min(), cc.max() - 50]
    assert max(extents) - min(extents) <= 1
    # Diagonal distortion stays small with the 16-neighbour stencil.
    radius = horizon * table.ros[0] / CELL_M
    k = int(radius / math.sqrt(2) * 0.9)
    expected = k * math.sqrt(2) * CELL_M / table.ros[0]
    assert arrival[50 - k, 50 + k] == pytest.approx(expected, rel=0.06)


def test_not_reached_is_nan_and_dtype():
    arrival = point_fire(50, 50, 25, 25, constant_table(5, 270, 10), 10)
    assert arrival.dtype == np.float32
    assert np.isnan(arrival).any()
    assert np.nanmax(arrival) <= 10
    assert arrival[25, 25] == 0


def test_unburnable_cells_block_spread():
    horizon = 120
    table = constant_table(7, 270, horizon)
    burnable = np.ones((40, 80), dtype=bool)
    burnable[:, 30] = False  # a firebreak column east of the ignition
    arrival = point_fire(40, 80, 20, 10, table, horizon, burnable)
    assert np.isfinite(arrival[20, 29])
    assert np.all(np.isnan(arrival[:, 30:]))
