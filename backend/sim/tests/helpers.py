"""Test helpers for the wildfire sim."""

from __future__ import annotations

import math
from typing import Optional

from backend.sim.engine.grid import TO_UTM
from backend.sim.wildfire import HORIZON_MIN, WildfireSim


def arrival_min(sim: WildfireSim, lat: float, lon: float, horizon_min: int = HORIZON_MIN) -> Optional[int]:
    """Sim minute the fire reaches (lat, lon), rounded down, or None if not within
    horizon_min minutes from now (or outside the fire domain). Reruns the fire
    further ahead first if needed, as routing does."""
    now = sim.minutes
    result = sim._covering(now + horizon_min)
    west, south, east, north = result.bbox
    if not (west <= lon <= east and south <= lat <= north):
        return None
    row, col = result.grid.cell_of(*TO_UTM.transform(lon, lat))
    row, col = min(row, result.grid.rows - 1), min(col, result.grid.cols - 1)
    minute = result.arrival_grid()[row, col]
    if math.isnan(minute) or minute > now + horizon_min:
        return None
    return int(math.floor(minute))
