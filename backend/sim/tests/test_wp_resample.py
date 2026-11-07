import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.sim.weatherpipe import openweather
from backend.sim.weatherpipe.obs import make_obs, merge_obs
from backend.sim.weatherpipe.resample import CoverageError, build_weather_series

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)


def obs_at(minutes, speed, direction, temp=20, rh=30, precip=0):
    return make_obs(T0 + timedelta(minutes=minutes), speed, direction, temp, rh, precip)


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def test_vector_interpolation_through_north():
    series = build_weather_series([obs_at(-60, 5, 350), obs_at(60, 5, 10)], T0, 60)
    assert series[0]["wind_dir_deg"] == 0
    assert series[0]["wind_speed_ms"] == pytest.approx(4.9)  # 5·cos(10°)


def test_opposite_winds_cancel():
    # Documented behaviour: halfway between 5 m/s from 90° and 5 m/s from 270° the
    # vectors cancel, so the interpolated wind is ~0 m/s (a lull), not 5 m/s.
    series = build_weather_series([obs_at(-60, 5, 90), obs_at(60, 5, 270)], T0, 60)
    assert series[0]["wind_speed_ms"] == pytest.approx(0.0, abs=0.05)


def test_scalars_interpolate_linearly():
    series = build_weather_series([obs_at(0, 5, 90, temp=10, rh=20, precip=0), obs_at(120, 5, 90, temp=20, rh=40, precip=2)], T0, 120)
    assert series[1] == {"t_min": 60, "wind_speed_ms": 5.0, "wind_dir_deg": 90, "temp_c": 15.0, "rh_pct": 30.0, "precip_mm": 1.0}


@pytest.mark.parametrize("horizon", [60, 300, 360, 361])
def test_series_shape(horizon):
    fc = openweather.obs_from_forecast_3h(json.loads((FIXTURES / "owm_forecast_3h.json").read_text()))
    current = openweather.obs_from_current(json.loads((FIXTURES / "owm_current.json").read_text()))
    series = build_weather_series(merge_obs(current, fc), T0, horizon)
    assert [e["t_min"] for e in series] == list(range(0, series[-1]["t_min"] + 1, 60))
    assert series[0]["t_min"] == 0 and series[-1]["t_min"] >= horizon
    for e in series:
        assert set(e) == {"t_min", "wind_speed_ms", "wind_dir_deg", "temp_c", "rh_pct", "precip_mm"}
        assert all(v is not None for v in e.values())
        assert isinstance(e["t_min"], int) and isinstance(e["wind_dir_deg"], int)
        assert 0 <= e["wind_dir_deg"] < 360


def test_holds_ends_within_three_hours():
    series = build_weather_series([obs_at(60, 4, 200), obs_at(120, 6, 200)], T0, 300)
    assert series[0]["wind_speed_ms"] == 4.0      # 1 h before first obs: held
    assert series[-1]["wind_speed_ms"] == 6.0     # 3 h after last obs: held


def test_gap_over_three_hours_raises():
    with pytest.raises(CoverageError, match="does not reach"):
        build_weather_series([obs_at(0, 4, 200), obs_at(60, 6, 200)], T0, 360)
    with pytest.raises(CoverageError):
        build_weather_series([obs_at(200, 4, 200), obs_at(400, 6, 200)], T0, 360)


def test_naive_t0_rejected():
    with pytest.raises(ValueError, match="naive"):
        build_weather_series([obs_at(0, 4, 200)], datetime(2026, 11, 8, 20), 60)


def test_non_utc_t0_rejected():
    tz = timezone(timedelta(hours=-7))
    with pytest.raises(ValueError, match="UTC"):
        build_weather_series([obs_at(0, 4, 200)], datetime(2026, 11, 8, 13, tzinfo=tz), 60)
