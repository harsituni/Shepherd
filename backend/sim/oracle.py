"""ForecastOracle: one frozen snapshot of the fire forecast, for routing.

Routing reads the sim only through this object. A request takes one snapshot and
uses it throughout, so it never mixes two forecasts even if the sim reruns
mid-request. The arrays are read-only and shared between snapshots of the same
fire run.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

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


def validation_error(oracle):
    """Validate snapshot structure before indexing or projecting it.

    Bad cell values are handled locally by the routing judge: an invalid cell
    elsewhere must not invalidate a covered journey. +inf alone means unreached
    within the horizon; NaN, -inf, negative and beyond-horizon arrivals are unknown.
    Returning a reason lets routing retain geometry with an indeterminate status.
    """
    try:
        for name in ("sim_time", "covers_until_sim_min", "wind_kmh", "wind_from_deg",
                     "x0", "y0", "cell_m"):
            value = getattr(oracle, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                return f"{name} must be finite and numeric"
        if oracle.sim_time < 0 or oracle.covers_until_sim_min < 0:
            return "simulation time and forecast horizon must be nonnegative"
        if oracle.cell_m <= 0:
            return "cell_m must be positive"
        if oracle.wind_kmh < 0 or not 0 <= oracle.wind_from_deg <= 360:
            return "invalid forecast wind metadata"
        for name in ("version", "nrows", "ncols"):
            value = getattr(oracle, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
                return f"{name} must be a positive integer"
        size = oracle.nrows * oracle.ncols
        if size > 2_000_000:
            return "forecast exceeds the engine's two-million-cell limit"
        if not all(math.isfinite(v) for v in (
                oracle.x0 + oracle.ncols * oracle.cell_m,
                oracle.y0 - oracle.nrows * oracle.cell_m)):
            return "invalid grid extent"
        if oracle.crs != "EPSG:32612":
            return "unsupported forecast CRS"
        if oracle.band not in ("p50", "p10") or not isinstance(oracle.run_id, str) or not oracle.run_id:
            return "invalid forecast band or run_id"
        if (not isinstance(oracle.arrival, np.ndarray) or oracle.arrival.shape != (size,)
                or oracle.arrival.dtype.kind not in "fiu"):
            return "arrival must be a flat numeric array matching the grid"
        if (not isinstance(oracle.in_domain, np.ndarray) or oracle.in_domain.shape != (size,)
                or oracle.in_domain.dtype != np.dtype(bool)):
            return "in_domain must be a flat boolean array matching the grid"
    except (AttributeError, TypeError, ValueError, OverflowError):
        return "malformed forecast snapshot"
    return None
