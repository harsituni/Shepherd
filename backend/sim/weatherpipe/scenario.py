"""Scenario config → Contract A, forecast updates and run ids.

Contract A is validated with the engine's own model (backend.sim.engine.contracts.Scenario),
so anything built here is exactly what run_engine accepts. On top of that this module
checks what the pipeline promises: an hourly series from t_min 0 to >= horizon_min,
every field present, no nulls.
"""

import copy
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from backend.sim.engine.contracts import FbpParams, PerimeterGeometry, Scenario
from backend.sim.weatherpipe.conventions import SCHEMA, SERIES_STEP_MIN, iso_z, require_utc

WEATHER_FIELDS = ("t_min", "wind_speed_ms", "wind_dir_deg", "temp_c", "rh_pct", "precip_mm")
# Everything a forecast update must leave untouched.
UPDATE_FROZEN = ("schema", "scenario_id", "t0", "bbox", "initial_perimeter",
                 "horizon_min", "step_min", "n_ensemble", "fbp", "cell_m", "integration_step_min", "ensemble_seed")
UPDATE_MAY_CHANGE = {"weather", "run_id", "weather_source", "revision_of"}


class WindShift(BaseModel):
    start_min: int = Field(ge=0)
    ramp_min: int = Field(ge=0)
    rotate_deg: float
    speed_factor: float = Field(gt=0)


class ScenarioConfig(BaseModel):
    """Hand-written per-city config: scenarios/{scenario_id}.json."""
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    bbox: tuple[float, float, float, float]
    initial_perimeter: PerimeterGeometry
    horizon_min: int = Field(gt=0)
    step_min: int = Field(gt=0)
    n_ensemble: int = Field(ge=1)
    fbp: FbpParams = Field(default_factory=FbpParams)
    cell_m: int = Field(default=100, ge=1)
    integration_step_min: float = Field(default=0.25, ge=0.001, le=60)
    ensemble_seed: int = Field(default=0, ge=0)
    weather_default_source: str
    wind_shift: WindShift | None = None


def load_config(path) -> ScenarioConfig:
    """Read a config; a relative canned:/cache: path resolves against the config's folder."""
    path = Path(path)
    config = ScenarioConfig.model_validate_json(path.read_text())
    kind, sep, target = config.weather_default_source.partition(":")
    if kind in ("canned", "cache") and sep and target != "latest" and not Path(target).is_absolute():
        resolved = (path.parent / target).resolve()
        config = config.model_copy(update={"weather_default_source": f"{kind}:{resolved}"})
    return config


def check_weather_series(weather: list[dict], horizon_min: int) -> None:
    if not weather:
        raise ValueError("weather is empty")
    for i, entry in enumerate(weather):
        for field in WEATHER_FIELDS:
            if entry.get(field) is None:
                raise ValueError(f"weather[{i}].{field} is missing or null")
        if not isinstance(entry["t_min"], int):
            raise ValueError(f"weather[{i}].t_min must be an integer")
        if entry["t_min"] != i * SERIES_STEP_MIN:
            raise ValueError(f"weather[{i}].t_min = {entry['t_min']}, expected hourly from 0")
        if not 0 <= entry["wind_dir_deg"] < 360:
            raise ValueError(f"weather[{i}].wind_dir_deg must be in [0, 360)")
    if weather[-1]["t_min"] < horizon_min:
        raise ValueError(f"weather ends at t_min {weather[-1]['t_min']}, before horizon_min {horizon_min}")


def validate_contract_a(scenario: dict) -> dict:
    """Raise if the engine would reject this scenario or the weather series is malformed."""
    Scenario.model_validate(scenario)
    check_weather_series(scenario["weather"], scenario["horizon_min"])
    return scenario


def build_scenario(config, weather: list[dict], t0: datetime, run_id: str,
                   weather_source: dict | None = None) -> dict:
    """Assemble and validate a full Contract A dict."""
    if not isinstance(config, ScenarioConfig):
        config = ScenarioConfig.model_validate(config)
    scenario = {
        "schema": SCHEMA,
        "scenario_id": config.scenario_id,
        "run_id": run_id,
        "t0": iso_z(require_utc(t0)),
        "horizon_min": config.horizon_min,
        "step_min": config.step_min,
        "bbox": list(config.bbox),
        "initial_perimeter": config.initial_perimeter.model_dump(),
        "weather": copy.deepcopy(weather),
        "n_ensemble": config.n_ensemble,
        "cell_m": config.cell_m,
        "integration_step_min": config.integration_step_min,
        "ensemble_seed": config.ensemble_seed,
        "fbp": config.fbp.model_dump(),
        "weather_source": copy.deepcopy(weather_source) if weather_source else {"provider": "unspecified"},
    }
    return validate_contract_a(scenario)


def check_forecast_update(base: dict, update: dict) -> None:
    """A forecast update keeps t0, bbox, perimeter, horizon, step and fbp; only
    weather, run_id and weather_source may differ."""
    for key in UPDATE_FROZEN:
        if base.get(key) != update.get(key):
            raise ValueError(f"forecast update changed {key!r}; only {sorted(UPDATE_MAY_CHANGE)} may differ")
    extra = set(base) ^ set(update)
    if extra - UPDATE_MAY_CHANGE:
        raise ValueError(f"forecast update adds or drops fields {sorted(extra - UPDATE_MAY_CHANGE)}")
    if base["run_id"] == update["run_id"]:
        raise ValueError("forecast update needs a new run_id")


def make_forecast_update(base_scenario: dict, new_weather: list[dict], run_id: str,
                         weather_source: dict | None = None) -> dict:
    update = copy.deepcopy(base_scenario)
    update["weather"] = copy.deepcopy(new_weather)
    update["run_id"] = run_id
    update["revision_of"] = base_scenario["run_id"]
    update["weather_source"] = copy.deepcopy(weather_source) if weather_source else {
        **base_scenario.get("weather_source", {}),
        "updated_from_run_id": base_scenario["run_id"],
    }
    check_forecast_update(base_scenario, update)
    return validate_contract_a(update)


def next_run_id(scenario_id: str, runs_dir: Path = Path("runs")) -> str:
    """'{scenario_id}-r{n}', n = 1 + highest existing; deterministic, no timestamps."""
    pattern = re.compile(rf"^{re.escape(scenario_id)}-r(\d+)$")
    runs_dir = Path(runs_dir)
    taken = [
        int(m.group(1))
        for p in (runs_dir.iterdir() if runs_dir.is_dir() else [])
        if (m := pattern.match(p.name))
    ]
    return f"{scenario_id}-r{max(taken, default=0) + 1}"


def write_scenario(scenario: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scenario, indent=2) + "\n")
    return path
