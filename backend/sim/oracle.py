"""ForecastOracle: one frozen snapshot of the fire forecast, for routing.

Routing reads the sim only through this object. A request takes one snapshot and
uses it throughout, so it never mixes two forecasts even if the sim reruns
mid-request. The arrays are read-only and shared between snapshots of the same
fire run.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, eq=False)
class ForecastOracle:
    version: int                  # unique per fire run; bumps on every rerun (wind change, lookahead)
    run_id: str
    band: str                     # "p50": the median arrival
    sim_time: int                 # the sim minute this snapshot was taken at
    covers_until_sim_min: float   # last sim minute the run models
    wind_kmh: float               # wind blowing at sim_time
    wind_from_deg: float
    x0: float                     # grid origin: outer top-left corner, UTM zone 12N metres
    y0: float
    cell_m: float
    nrows: int
    ncols: int
    arrival: np.ndarray           # (nrows * ncols,) sim minutes; +inf = not reached by covers_until
    in_domain: np.ndarray         # (nrows * ncols,) bool: the fire is modelled in this cell
    crs: str = "EPSG:32612"
