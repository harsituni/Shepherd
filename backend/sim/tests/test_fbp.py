import math

import numpy as np
import pytest

from backend.sim.engine import fbp

# FFMC 92, BUI 90, WS 25 km/h, M-1, pc 50 (hand-computed sanity values).
SANITY = dict(fuel_type="M-1", pc=50, ffmc=92, bui=90)


def test_sanity_values():
    assert fbp.isi(92, 25) == pytest.approx(20.0, abs=0.5)
    rates = fbp.spread_rates(ws_kmh=25, **SANITY)
    assert 20.0 <= rates.ros <= 21.0
    assert rates.lb == pytest.approx(3.2, abs=0.05)


def test_ffmc_moisture():
    assert fbp.ffmc_to_moisture(92) == pytest.approx(8.749, abs=1e-3)


def test_wind_function_continuous_at_40():
    assert fbp.wind_function(40) == pytest.approx(fbp.wind_function(40.0001), rel=1e-3)


def test_ros_increases_with_wind_and_ffmc():
    winds = np.linspace(0, 60, 31)
    assert np.all(np.diff(fbp.ros("M-1", 50, 92, 90, winds)) > 0)
    ffmcs = np.linspace(80, 98, 19)
    assert np.all(np.diff(fbp.ros("M-1", 50, ffmcs, 90, 25)) > 0)


def test_m1_faster_than_m2():
    assert fbp.ros("M-1", 50, 92, 90, 25) > fbp.ros("M-2", 50, 92, 90, 25)


@pytest.mark.parametrize("ws", [5, 15, 25, 45])
def test_bros_lt_fros_lt_ros(ws):
    r = fbp.spread_rates(ws_kmh=ws, **SANITY)
    assert r.bros < r.fros < r.ros


def test_calm_is_circle():
    r = fbp.spread_rates(ws_kmh=0, **SANITY)
    assert r.lb == pytest.approx(1.0)
    assert r.ros == pytest.approx(r.bros) == pytest.approx(r.fros)
    assert fbp.length_to_breadth(1e-6) == pytest.approx(1.0, abs=1e-6)


def test_zero_bui_means_no_spread():
    r = fbp.spread_rates(ws_kmh=25, fuel_type="M-1", pc=50, ffmc=92, bui=0)
    assert r.ros == 0
    assert fbp.directional_ros(r.ros, r.bros, r.fros, 0.3) == 0


def test_unknown_fuel_type():
    with pytest.raises(ValueError, match="fuel_type"):
        fbp.ros("C-2", 50, 92, 90, 25)


def test_directional_ros_identities():
    r = fbp.spread_rates(ws_kmh=25, **SANITY)
    rate = lambda theta: fbp.directional_ros(r.ros, r.bros, r.fros, theta)
    assert rate(0) == pytest.approx(r.ros)
    assert rate(math.pi) == pytest.approx(r.bros)
    for theta in (0.2, 1.0, 2.0, 3.0):
        assert rate(theta) == pytest.approx(rate(-theta))
    thetas = np.linspace(0, math.pi, 181)
    assert np.all(np.diff(rate(thetas)) < 0)
