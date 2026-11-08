"""Contract A (scenario in) models, plus writers and loaders for B1 and B2 (out).

Validation fails loudly: a missing or malformed field raises a pydantic
ValidationError whose message names the field. Unknown fields and non-finite numerical values are rejected.
"""

import json
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from pydantic import (
    AwareDatetime,
    ConfigDict,
    BaseModel,
    Field,
    field_validator,
    model_validator,
)
from shapely.geometry import box, shape

SCHEMA = "v1"
B1_HEADER = "b1_header.json"
FRAMES = "frames.geojson"
LAYERS = {"arrival_p50": "arrival_p50.npy", "arrival_p10": "arrival_p10.npy"}


class ValidatedModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class WeatherEntry(ValidatedModel):
    t_min: int = Field(ge=0)
    wind_speed_ms: float = Field(ge=0, le=60)
    wind_dir_deg: float = Field(ge=0, le=360)
    # Validated but unused by the v1 spread model (fuel moisture is fixed via FFMC/BUI).
    temp_c: float = Field(ge=-60, le=60)
    rh_pct: float = Field(ge=0, le=100)
    precip_mm: float = Field(ge=0)


class FbpParams(ValidatedModel):
    fuel_type: Literal["M-1", "M-2"] = "M-1"
    pc: float = Field(default=50, ge=0, le=100)
    ffmc: float = Field(default=92, ge=0, le=101)
    bui: float = Field(default=90, ge=0)


class PerimeterGeometry(ValidatedModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list

    @model_validator(mode="after")
    def _valid_shape(self):
        try:
            geom = shape(self.model_dump())
        except Exception as exc:
            raise ValueError(f"not a valid GeoJSON {self.type}: {exc}") from exc
        if geom.is_empty or not geom.is_valid:
            raise ValueError("geometry is empty or invalid (self-intersecting?)")
        return self

    def to_shapely(self):
        return shape(self.model_dump())


class IgnitionPoint(ValidatedModel):
    lat: float = Field(ge=0, le=84)
    lon: float = Field(ge=-114, le=-108)


class Scenario(ValidatedModel):
    schema_: Literal["v1"] = Field(alias="schema")
    scenario_id: str = Field(min_length=1)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    t0: AwareDatetime
    horizon_min: int = Field(gt=0)
    step_min: int = Field(gt=0)
    bbox: tuple[float, float, float, float]
    initial_perimeter: Optional[PerimeterGeometry] = None
    ignition: Optional[IgnitionPoint] = None
    weather: list[WeatherEntry] = Field(min_length=1)
    n_ensemble: int = Field(default=1, ge=1, le=100)
    cell_m: int = Field(default=100, ge=1)
    integration_step_min: float = Field(default=0.25, ge=0.001, le=60)
    ensemble_seed: int = Field(default=0, ge=0)
    weather_end_policy: Literal["error", "hold"] = "error"
    weather_source: dict = Field(default_factory=dict)
    execution_mode: Literal["recompute"] = "recompute"
    revision_of: Optional[str] = None
    fbp: FbpParams = Field(default_factory=FbpParams)

    @field_validator("t0")
    @classmethod
    def _utc(cls, t0):
        if t0.utcoffset().total_seconds() != 0:
            raise ValueError("t0 must be UTC (e.g. 2026-11-08T20:00:00Z)")
        return t0

    @field_validator("bbox")
    @classmethod
    def _bbox_order(cls, bbox):
        min_lon, min_lat, max_lon, max_lat = bbox
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
        if not (-114 <= min_lon < max_lon <= -108 and 0 <= min_lat < max_lat <= 84):
            raise ValueError("domain must be within UTM zone 12N (-114..-108 lon, 0..84 lat)")
        return bbox

    @field_validator("weather")
    @classmethod
    def _weather_order(cls, weather):
        if weather[0].t_min != 0:
            raise ValueError("first weather entry must have t_min = 0")
        times = [w.t_min for w in weather]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("weather must be sorted by strictly increasing t_min")
        return weather

    @model_validator(mode="after")
    def _perimeter_in_bbox(self):
        if self.step_min > self.horizon_min:
            raise ValueError("step_min must not exceed horizon_min")
        if (self.initial_perimeter is None) == (self.ignition is None):
            raise ValueError("provide exactly one of initial_perimeter or ignition")
        from shapely.geometry import Point
        initial = (self.initial_perimeter.to_shapely() if self.initial_perimeter is not None
                   else Point(self.ignition.lon, self.ignition.lat))
        if not box(*self.bbox).covers(initial):
            raise ValueError("initial_perimeter or ignition lies outside bbox")
        if self.weather[-1].t_min < self.horizon_min and self.weather_end_policy == "error":
            raise ValueError("weather ends before horizon_min; explicitly choose weather_end_policy='hold' to extrapolate")
        return self


def load_scenario(source) -> Scenario:
    """Contract A from a dict, a JSON string, or a path to a JSON file."""
    if isinstance(source, Scenario):
        source = source.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("{")):
        source = Path(source).read_text()
    if isinstance(source, str):
        source = json.loads(source)
    return Scenario.model_validate(source)


class B1Header(BaseModel):
    schema_: Literal["v1"] = Field(alias="schema")
    run_id: str
    crs: Literal["EPSG:32612"]
    origin_xy: tuple[float, float]
    cell_m: int = Field(gt=0)
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    origin_is: Literal["top-left"]
    layers: dict[str, str]


def _write_json(path, data, indent=2):
    path.write_text(json.dumps(data, indent=indent) + "\n")


def write_b1(out_dir: Path, run_id, grid, p50, p10) -> Path:
    header = {
        "schema": SCHEMA,
        "run_id": run_id,
        "crs": "EPSG:32612",
        "origin_xy": [grid.origin_x, grid.origin_y],
        "cell_m": grid.cell_m,
        "rows": grid.rows,
        "cols": grid.cols,
        "origin_is": "top-left",
        "layers": dict(LAYERS),
    }
    np.save(out_dir / LAYERS["arrival_p50"], p50.astype(np.float32))
    np.save(out_dir / LAYERS["arrival_p10"], p10.astype(np.float32))
    path = out_dir / B1_HEADER
    _write_json(path, header)
    return path


def load_b1(out_dir: Path):
    """(header, {layer: array}) for a B1 output directory, checking shape and dtype."""
    out_dir = Path(out_dir)
    header = B1Header.model_validate_json((out_dir / B1_HEADER).read_text())
    arrays = {}
    for layer, filename in header.layers.items():
        arr = np.load(out_dir / filename)
        if arr.dtype != np.float32 or arr.shape != (header.rows, header.cols):
            raise ValueError(
                f"{filename}: expected float32 {(header.rows, header.cols)}, "
                f"got {arr.dtype} {arr.shape}"
            )
        arrays[layer] = arr
    return header, arrays


def write_frames(out_dir: Path, run_id, features) -> Path:
    path = out_dir / FRAMES
    _write_json(path, {"type": "FeatureCollection", "run_id": run_id, "features": features}, indent=None)
    return path


def write_run_meta(out_dir: Path, meta) -> Path:
    path = out_dir / "run_meta.json"
    _write_json(path, meta)
    return path
