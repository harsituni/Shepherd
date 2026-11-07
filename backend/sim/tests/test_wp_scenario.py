import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.sim.engine.contracts import load_scenario
from backend.sim.weatherpipe.scenario import (
    build_scenario,
    check_forecast_update,
    load_config,
    make_forecast_update,
    next_run_id,
    write_scenario,
)
from backend.sim.weatherpipe.shift import apply_wind_shift

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
CONFIG = SCENARIOS / "edm-demo-1.json"
T0 = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)


def weather(n=7, speed=6.0, direction=270):
    return [{"t_min": 60 * k, "wind_speed_ms": speed, "wind_dir_deg": direction, "temp_c": 20.0, "rh_pct": 20.0, "precip_mm": 0.0} for k in range(n)]


@pytest.fixture
def base():
    return build_scenario(load_config(CONFIG), weather(), T0, "edm-demo-1-r1", {"provider": "canned"})


def test_build_scenario_is_engine_valid(base):
    parsed = load_scenario(base)           # the engine's own Contract A model
    assert parsed.run_id == "edm-demo-1-r1"
    assert base["t0"] == "2026-11-08T20:00:00Z"
    assert base["schema"] == "v1"
    assert base["fbp"] == {"fuel_type": "M-1", "pc": 50.0, "ffmc": 92.0, "bui": 90.0}
    assert base["weather_source"] == {"provider": "canned"}


def test_build_scenario_rejects_naive_t0():
    with pytest.raises(ValueError, match="naive"):
        build_scenario(load_config(CONFIG), weather(), datetime(2026, 11, 8, 20), "r1")


@pytest.mark.parametrize("bad, message", [
    (weather(n=6), "before horizon_min"),
    ([{**w, "temp_c": None} if w["t_min"] == 60 else w for w in weather()], r"weather\W+1\W+temp_c"),
    ([{**w, "t_min": 30} if w["t_min"] == 60 else w for w in weather()], "hourly"),
])
def test_build_scenario_rejects_bad_weather(bad, message):
    with pytest.raises((ValueError, ValidationError), match=message):
        build_scenario(load_config(CONFIG), bad, T0, "r1")


def test_edmonton_defaults_to_live_openweather():
    assert load_config(CONFIG).weather_default_source == "openweather:forecast-3h"


def test_config_paths_resolve_from_config_folder(tmp_path):
    config = json.loads(CONFIG.read_text())
    config["weather_default_source"] = "canned:city.weather.json"
    path = tmp_path / "city.json"
    path.write_text(json.dumps(config))
    assert load_config(path).weather_default_source == f"canned:{(tmp_path / 'city.weather.json').resolve()}"


def test_forecast_update_changes_only_weather(base):
    update = make_forecast_update(base, apply_wind_shift(base["weather"], 120, 60, -60, 1.4), "edm-demo-1-r2")
    assert update["run_id"] == "edm-demo-1-r2"
    assert update["weather"] != base["weather"]
    assert update["weather_source"]["updated_from_run_id"] == "edm-demo-1-r1"
    for key in ("t0", "bbox", "initial_perimeter", "horizon_min", "step_min", "fbp"):
        assert update[key] == base[key]
    load_scenario(update)


@pytest.mark.parametrize("key, value", [("t0", "2026-11-08T21:00:00Z"), ("bbox", [-113.8, 53.42, -113.43, 53.58]), ("fbp", {"fuel_type": "M-2"})])
def test_forecast_update_rejects_frozen_change(base, key, value):
    update = copy.deepcopy(base)
    update["run_id"] = "edm-demo-1-r2"
    update[key] = value
    with pytest.raises(ValueError, match=key):
        check_forecast_update(base, update)


def test_forecast_update_needs_new_run_id(base):
    with pytest.raises(ValueError, match="run_id"):
        make_forecast_update(base, base["weather"], base["run_id"])


def test_next_run_id(tmp_path):
    assert next_run_id("edm-demo-1", tmp_path / "missing") == "edm-demo-1-r1"
    for name in ("edm-demo-1-r1", "edm-demo-1-r3", "edm-demo-10-r9", "other-r7"):
        (tmp_path / name).mkdir()
    assert next_run_id("edm-demo-1", tmp_path) == "edm-demo-1-r4"


def test_write_scenario_round_trips(base, tmp_path):
    path = write_scenario(base, tmp_path / "a" / "scenario.json")
    assert json.loads(path.read_text()) == base
    load_scenario(path)
