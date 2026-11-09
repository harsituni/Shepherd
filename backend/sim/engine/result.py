"""A finished simulation: its grid and fire-arrival minutes. Read-only."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.sim.engine.grid import Grid


def immutable_array(array):
    """Bytes-backed storage prevents even setflags(write=True) from modifying it."""
    a = np.asarray(array, dtype=np.float32)
    return np.frombuffer(a.tobytes(), dtype=np.float32).reshape(a.shape)


@dataclass(frozen=True)
class SimulationResult:
    grid: Grid
    bbox: tuple
    horizon_min: int
    _arrival: np.ndarray = field(repr=False)

    def __post_init__(self):
        if self._arrival.shape != self.grid.shape:
            raise ValueError('arrival array shape does not match grid')
        object.__setattr__(self, '_arrival', immutable_array(self._arrival))

    def arrival_grid(self):
        """(rows, cols) float32 minutes since t0 the fire reaches each cell; NaN if not within the horizon."""
        return self._arrival
