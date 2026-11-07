import pytest

from backend.sim.engine import fbp
from backend.sim.engine.contracts import FbpParams, WeatherEntry
from backend.sim.engine.weather import (
    build_weather_table,
    interpolate_wind,
    ms_to_kmh,
    spread_bearing,
    uv_to_wind,
    wind_to_uv,
)


def entry(t, speed, direction):
    return WeatherEntry(t_min=t, wind_speed_ms=speed, wind_dir_deg=direction, temp_c=20, rh_pct=20, precip_mm=0)


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


@pytest.mark.parametrize("wind_from, toward", [(270, 90), (0, 180), (90, 270), (180, 0), (315, 135)])
def test_spread_bearing(wind_from, toward):
    assert spread_bearing(wind_from) == toward


def test_units():
    assert ms_to_kmh(10) == pytest.approx(36)


@pytest.mark.parametrize("direction", [0, 45, 135, 270, 350])
def test_uv_round_trip(direction):
    speed, back = uv_to_wind(*wind_to_uv(5, direction))
    assert speed == pytest.approx(5)
    assert angle_diff(back, direction) < 1e-9


def test_wind_from_west_moves_air_east():
    u, v = wind_to_uv(5, 270)
    assert u == pytest.approx(5)
    assert v == pytest.approx(0, abs=1e-9)


def test_vector_interpolation_through_north():
    weather = [entry(0, 5, 350), entry(60, 5, 10)]
    speed, direction = interpolate_wind(weather, 30)
    assert angle_diff(direction, 0) < 1e-9
    assert speed < 5


def test_interpolation_holds_ends():
    weather = [entry(0, 4, 270), entry(60, 8, 250)]
    assert interpolate_wind(weather, -5) == (4, 270)
    assert interpolate_wind(weather, 90) == (8, 250)
    assert interpolate_wind(weather, 60) == (8, 250)


def test_weather_table_uses_kmh_in_fbp():
    fuel = FbpParams()
    table = build_weather_table([entry(0, 6.5, 270)], fuel, horizon_min=10)
    assert len(table) == 11
    assert table.ros[0] == pytest.approx(fbp.ros("M-1", 50, 92, 90, 6.5 * 3.6))
    assert table.spread_bearing_deg[5] == pytest.approx(90)
    assert table.index(10.7) == 10
    assert table.index(999) == 10
