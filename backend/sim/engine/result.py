"""Completed, effectively immutable simulation results. No live simulation state."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np

from backend.sim.engine.frames import burned_geometry
from backend.sim.engine.grid import Grid, TO_UTM


@dataclass(frozen=True)
class ArrivalQuery:
    status: Literal['arrival', 'not_reached', 'outside_domain', 'invalid_input', 'unavailable']
    arrival_min: float | None
    burned: bool | None
    query_min: float | None
    horizon_min: float
    band: str
    row: int | None = None
    col: int | None = None
    message: str | None = None


def immutable_array(array):
    """Bytes-backed storage prevents even setflags(write=True) from modifying it."""
    a = np.asarray(array, dtype=np.float32)
    return np.frombuffer(a.tobytes(), dtype=np.float32).reshape(a.shape)


@dataclass(frozen=True)
class SimulationResult:
    grid: Grid
    bbox: tuple
    horizon_min: int
    _p50: np.ndarray = field(repr=False)
    _p10: np.ndarray = field(repr=False)
    _metadata_json: str = field(repr=False)
    _scenario_json: str = field(repr=False)

    def __post_init__(self):
        for name in ('_p50', '_p10'):
            a = getattr(self, name)
            if a.shape != self.grid.shape:
                raise ValueError('arrival array shape does not match grid')
            object.__setattr__(self, name, immutable_array(a))

    @property
    def metadata(self):
        """Detached JSON-compatible copy; changing it cannot change the result."""
        return json.loads(self._metadata_json)

    @property
    def scenario(self):
        return json.loads(self._scenario_json)

    def arrival_grid(self, band='p50'):
        if band not in ('p50', 'p10'):
            raise ValueError("band must be 'p50' or 'p10'")
        return self._p50 if band == 'p50' else self._p10

    def arrival_at(self, lat, lon, *, minute=None, band='p50') -> ArrivalQuery:
        """Lookup containing raster cell; times always refer to original t0.

        `burned=False` is only returned for a valid time inside the modeled
        horizon. For later times, an unreached cell has burned=None (unknown).
        Known arrivals are never discarded by a caller's query time.
        """
        def answer(status, arrival=None, burned=None, row=None, col=None, message=None):
            return ArrivalQuery(status, arrival, burned, query_time, self.horizon_min, band, row, col, message)
        query_time = None
        try:
            lat, lon = float(lat), float(lon)
            if minute is not None:
                query_time = float(minute)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (query_time is not None and (not math.isfinite(query_time) or query_time < 0)):
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            query_time = None
            return answer('invalid_input', message='finite geographic coordinates and nonnegative minute required')
        if band not in ('p50', 'p10'):
            return answer('invalid_input', message='unknown arrival band')
        west, south, east, north = self.bbox
        if not (west <= lon <= east and south <= lat <= north):
            return answer('outside_domain', message='outside scenario bbox; no prediction')
        x, y = TO_UTM.transform(lon, lat)
        row, col = self.grid.cell_of(x, y)
        # Geographic bbox is closed; handle exact outer raster boundaries.
        if row == self.grid.rows and abs(y - (self.grid.origin_y - row * self.grid.cell_m)) < 1e-6:
            row -= 1
        if col == self.grid.cols and abs(x - (self.grid.origin_x + col * self.grid.cell_m)) < 1e-6:
            col -= 1
        if not (0 <= row < self.grid.rows and 0 <= col < self.grid.cols):
            return answer('unavailable', message='coordinate outside raster coverage')
        at = float(self.arrival_grid(band)[row, col])
        if math.isnan(at):
            burned = False if query_time is not None and query_time <= self.horizon_min else None
            return answer('not_reached', burned=burned, row=row, col=col,
                          message='not reached within modeled horizon; not a safety guarantee')
        return answer('arrival', at, None if query_time is None else at <= query_time, row, col)

    def perimeter_at(self, minute, *, band='p50'):
        minute = float(minute)
        if not math.isfinite(minute) or not 0 <= minute <= self.horizon_min:
            raise ValueError('perimeter minute must be within modeled horizon')
        geometry = burned_geometry(self.arrival_grid(band) <= minute, self.grid, self.bbox)
        return {'type': 'Feature', 'properties': {'t_min': minute, 'band': band}, 'geometry': geometry}

    def frames_at(self, minutes, *, band='p50'):
        return {'type': 'FeatureCollection', 'run_id': self.metadata['run_id'],
                'features': [self.perimeter_at(t, band=band) for t in minutes]}

    def export(self, out_dir, *, minutes=None):
        from backend.sim.engine.export import export_result
        return export_result(self, Path(out_dir), minutes=minutes)

    @classmethod
    def load(cls, out_dir):
        from backend.sim.engine.export import load_result
        return load_result(Path(out_dir))
