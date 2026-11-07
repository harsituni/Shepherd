"""Point lookups on a B1 arrival grid: when does fire reach this lat/lon?

Usage:
    from backend.sim.engine.arrival import ArrivalGrid

    grid = ArrivalGrid.load("runs/fmm-demo-1-r1")   # reads arrival_p10 by default
    grid.arrival_min(lat=56.70, lon=-111.45)         # -> int minutes after t0, or None

Reads arrival_p10 (the early, pessimistic arrival) by default because routing
uses it for safety decisions. Minutes are floored, so the answer never says the
fire arrives later than the grid predicts.
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np

from backend.sim.engine.contracts import load_b1
from backend.sim.engine.grid import TO_UTM


class ArrivalGrid:
    def __init__(self, origin_xy, cell_m, arrival: np.ndarray):
        self.origin_x, self.origin_y = origin_xy
        self.cell_m = cell_m
        from backend.sim.engine.result import immutable_array
        self.arrival = immutable_array(arrival)
        self._result = None
        self._band = "p10"

    @classmethod
    def load(cls, out_dir: Path, layer: str = "arrival_p10") -> "ArrivalGrid":
        if (Path(out_dir) / "manifest.json").exists():
            from backend.sim.engine.result import SimulationResult
            result = SimulationResult.load(out_dir)
            band = layer.removeprefix("arrival_")
            obj = cls((result.grid.origin_x, result.grid.origin_y), result.grid.cell_m,
                      result.arrival_grid(band))
            obj._result, obj._band = result, band
            return obj
        header, arrays = load_b1(out_dir)
        return cls(header.origin_xy, header.cell_m, arrays[layer])

    def arrival_at(self, lat, lon, *, minute=None):
        """Structured query for current exports. Prefer SimulationResult directly."""
        if self._result is None:
            raise ValueError("legacy B1-only grid lacks domain/horizon metadata; load a current manifest export")
        return self._result.arrival_at(lat, lon, minute=minute, band=self._band)

    def arrival_min(self, lat: float, lon: float) -> Optional[int]:
        """Minutes after t0 when fire reaches (lat, lon); None if not within the
        horizon or outside the grid."""
        if self._result is not None:
            q = self.arrival_at(lat, lon)
            return math.floor(q.arrival_min) if q.status == "arrival" else None
        x, y = TO_UTM.transform(lon, lat)
        row = math.floor((self.origin_y - y) / self.cell_m)
        col = math.floor((x - self.origin_x) / self.cell_m)
        rows, cols = self.arrival.shape
        if not (0 <= row < rows and 0 <= col < cols):
            return None
        t = self.arrival[row, col]
        return None if np.isnan(t) else math.floor(t)
