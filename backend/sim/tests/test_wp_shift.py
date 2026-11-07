import json

import pytest

from backend.sim.weatherpipe.shift import apply_wind_shift


def weather(direction=270, speed=5.0):
    return [{"t_min": 60 * k, "wind_speed_ms": speed, "wind_dir_deg": direction, "temp_c": 20.0, "rh_pct": 20.0, "precip_mm": 0.0} for k in range(7)]


def test_before_start_identical_and_input_untouched():
    base = weather()
    snapshot = json.dumps(base)
    shifted = apply_wind_shift(base, start_min=120, ramp_min=60, rotate_deg=-60, speed_factor=1.4)
    assert json.dumps(base) == snapshot
    for a, b in zip(base, shifted):
        if a["t_min"] <= 120:
            assert json.dumps(a) == json.dumps(b)
    assert shifted is not base and shifted[0] is not base[0]


def test_rotation_wraps():
    shifted = apply_wind_shift(weather(direction=30), 0, 0, -60, 1.0)
    assert [e["wind_dir_deg"] for e in shifted[1:]] == [330] * 6
    assert apply_wind_shift(weather(direction=350), 0, 0, 30, 1.0)[1]["wind_dir_deg"] == 20


def test_ramp_is_linear():
    shifted = apply_wind_shift(weather(direction=270, speed=5.0), start_min=60, ramp_min=240, rotate_deg=-80, speed_factor=2.0)
    dirs = [e["wind_dir_deg"] for e in shifted]
    speeds = [e["wind_speed_ms"] for e in shifted]
    assert dirs == [270, 270, 250, 230, 210, 190, 190]
    assert speeds == [5.0, 5.0, 6.2, 7.5, 8.8, 10.0, 10.0]


def test_other_fields_unchanged():
    shifted = apply_wind_shift(weather(), 0, 60, -60, 1.4)
    for a, b in zip(weather(), shifted):
        assert {k: v for k, v in a.items() if k not in ("wind_dir_deg", "wind_speed_ms")} == \
               {k: v for k, v in b.items() if k not in ("wind_dir_deg", "wind_speed_ms")}
