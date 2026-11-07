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
        self.arrival = arrival

    @classmethod
    def load(cls, out_dir: Path, layer: str = "arrival_p10") -> "ArrivalGrid":
        header, arrays = load_b1(out_dir)
        return cls(header.origin_xy, header.cell_m, arrays[layer])

    def arrival_min(self, lat: float, lon: float) -> Optional[int]:
        """Minutes after t0 when fire reaches (lat, lon); None if not within the
        horizon or outside the grid."""
        x, y = TO_UTM.transform(lon, lat)
        row = math.floor((self.origin_y - y) / self.cell_m)
        col = math.floor((x - self.origin_x) / self.cell_m)
        rows, cols = self.arrival.shape
        if not (0 <= row < rows and 0 <= col < cols):
            return None
        t = self.arrival[row, col]
        return None if np.isnan(t) else math.floor(t)
