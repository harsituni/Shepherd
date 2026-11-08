"""Fire checks for routing v3: per-road deadlines and the cell-by-cell judge.

The contract's rule: a route is unsafe if the driver leaves any 100 m fire-grid
cell on it later than BUFFER_MIN minutes before the fire's forecast arrival there.

`EdgeFire` reduces every road to one number per forecast version, its deadline:
the latest sim minute a driver may enter it and still clear every cell in time.

    D_e = min_i (min(A_i, H) - BUFFER_MIN - d_i / v)

A_i is the fire's arrival in the edge's i-th cell, d_i the distance from the edge's
start to where it leaves that cell. Cells the fire doesn't reach within the
forecast window H have A = +inf. Unknown/invalid cells make the edge deadline
-inf. The whole-route judge additionally enforces the existing 90-minute
forecast reserve and bounds the departure deadline by it.

`judge()` then checks one whole route exactly, connector and shelter cell included,
and explains where it fails. Forecasts are not a safety guarantee.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np
from shapely.geometry import LineString, Point
from backend.sim.oracle import validation_error

from backend.routing.road_graph import (
    SPEED_KM_PER_MIN, TO_LONLAT, CellTable, FireGrid, RoadGraph, traverse_segment,
)

log = logging.getLogger(__name__)

BUFFER_MIN = 30
OK_MIN = 60
COVERAGE_SLACK_MIN = 90   # a trip must end this long before the forecast window does
EPS_MIN = 1e-6            # float noise; an exact-buffer arrival stays allowed
KEEP_VERSIONS = 2

CONNECTOR_NAME = "the connector"


def arrival_at_cells(oracle, flat: np.ndarray):
    """(arrival, unknown) per flat cell. Unknown cells (off the grid or outside the
    fire domain) read as +inf and are reported, never treated as forecast-clear."""
    flat = np.asarray(flat, dtype=np.int64)
    arrival = np.full(len(flat), np.inf)
    unknown = (flat < 0) | (flat >= len(oracle.arrival))
    on_grid = ~unknown
    arrival[on_grid] = oracle.arrival[flat[on_grid]]
    unknown[on_grid] = ~oracle.in_domain[flat[on_grid]]
    # Only +inf denotes a successfully modeled, unreached cell. Other invalid
    # values provide no evidence; finite arrivals must belong to this horizon.
    valid = np.isposinf(arrival) | (np.isfinite(arrival) & (arrival >= 0)
                                   & (arrival <= oracle.covers_until_sim_min))
    unknown |= ~valid
    arrival[unknown] = np.inf
    return arrival, unknown


@dataclass(frozen=True, eq=False)
class EdgeFire:
    """Fire arrays for one forecast version. Read-only once built."""
    oracle: object
    rg: RoadGraph
    table: CellTable
    cell_A: np.ndarray         # (entries,) arrival per cell-table entry
    cell_unknown: np.ndarray   # (entries,) no forecast for that cell
    edge_deadline: np.ndarray  # (E,) latest sim minute to enter each edge

    @property
    def version(self) -> int:
        return self.oracle.version

    @classmethod
    def for_oracle(cls, rg: RoadGraph, table: CellTable, oracle) -> "EdgeFire":
        """Built once per forecast version, even when requests arrive together."""
        error = validation_error(oracle)
        if error:
            raise ValueError(error)
        hit = _cached(rg, table, oracle)
        if hit is not None:
            return hit
        with _lock:
            hit = _cached(rg, table, oracle)
            if hit is not None:
                return hit
            if FireGrid.of(oracle) != table.grid:
                raise ValueError("cell table was built for a different fire grid")
            cell_A, cell_unknown = arrival_at_cells(oracle, table.cell_flat)
            # Unreached cells are bounded by the horizon, never safe forever.
            limit = np.minimum(cell_A, oracle.covers_until_sim_min) - BUFFER_MIN
            slack = limit - (table.cell_leave_m / 1000.0) / SPEED_KM_PER_MIN
            slack[cell_unknown] = -np.inf
            deadline = (np.minimum.reduceat(slack, table.cell_ptr[:-1])
                        if len(slack) else np.full(rg.n_edges, np.inf))
            for a in (cell_A, cell_unknown, deadline):
                a.flags.writeable = False
            built = cls(oracle, rg, table, cell_A, cell_unknown, deadline)
            if cell_unknown.any():
                log.warning("forecast %s has %d unknown/invalid road-cell entries",
                            oracle.version, int(cell_unknown.sum()))
            _recent.insert(0, built)
            del _recent[KEEP_VERSIONS:]
            return built


_lock = threading.Lock()
_recent: list = []


def _cached(rg, table, oracle):
    for fire in list(_recent):
        if (fire.rg is rg and fire.table is table and fire.oracle.version == oracle.version
                and fire.oracle.arrival is oracle.arrival
                and fire.oracle.in_domain is oracle.in_domain
                and fire.oracle.covers_until_sim_min == oracle.covers_until_sim_min):
            return fire
    return None


@dataclass(frozen=True, eq=False)
class RoutePath:
    """Modeled road journey, including directed origin/destination partial arcs.

    `access_verified` requires mapped, continuous access. Missing connections
    are never treated as zero-length traversable connectors. Direct unit callers
    must explicitly declare their modeled access; the app derives it from maps.
    """
    pin_ll: tuple             # (lon, lat)
    pin_xy: tuple
    join_ll: tuple            # where the connector meets the road
    join_xy: tuple
    edges: np.ndarray         # edge indices in travel order
    road_m: float
    shelter_ll: tuple
    shelter_xy: tuple
    shelter_name: str
    approximate: bool = False
    access: Optional[dict] = None
    access_verified: bool = False

    @property
    def connector_m(self) -> float:
        return float(math.hypot(self.join_xy[0] - self.pin_xy[0], self.join_xy[1] - self.pin_xy[1]))

    @property
    def total_m(self) -> float:
        return self.connector_m + self.road_m

    @property
    def total_min(self) -> float:
        return self.total_m / 1000.0 / SPEED_KM_PER_MIN


@dataclass(frozen=True)
class Judgement:
    status: str                         # ok | tight | blocked | indeterminate
    margin_min: Optional[int]
    leave_by_sim_min: Optional[int]
    clear_until_sim_min: Optional[int]
    reason: Optional[str]
    hazard_intercept: Optional[dict]
    shelter_threat_sim_min: Optional[int]
    forecast_complete: bool
    arrival_sim_min: float              # modeled travel; lower bound if access is incomplete


def clear(path: RoutePath, t_now: float) -> Judgement:
    """No fire running, with mapped access already established by the caller."""
    return Judgement("ok", None, None, None, None, None, None, True, t_now + path.total_min)


def viable(judgement: Judgement) -> bool:
    return judgement.status in ("ok", "tight") and judgement.forecast_complete


def indeterminate(path, t_now, reason, shelter_threat=None):
    return Judgement("indeterminate", None, None, None, reason, None, shelter_threat,
                     False, t_now + path.total_min)


def judge(path: RoutePath, t_now: float, oracle=None, edge_fire: Optional[EdgeFire] = None) -> Judgement:
    """Check every cell on the route against the 30-minute rule."""
    if oracle is None:
        return (clear(path, t_now) if path.access_verified else
                indeterminate(path, t_now, "Traversable origin, destination, or road-junction access is not established by the map."))
    error = validation_error(oracle)
    if error:
        return indeterminate(path, t_now, f"Invalid fire forecast: {error}.")
    if len(path.edges) and edge_fire is None:
        raise ValueError("a road route needs the EdgeFire for its forecast")
    if len(path.edges) and (edge_fire.version != oracle.version
                           or edge_fire.table.grid != FireGrid.of(oracle)
                           or edge_fire.oracle.arrival is not oracle.arrival
                           or edge_fire.oracle.in_domain is not oracle.in_domain
                           or edge_fire.oracle.covers_until_sim_min != oracle.covers_until_sim_min):
        return indeterminate(path, t_now, "Road hazards do not match this forecast.")
    grid = FireGrid.of(oracle)

    # Cells in travel order: connector, each edge's cells, then the shelter's own cell.
    c_flat, _, c_leave = traverse_segment(path.pin_xy, path.join_xy, grid)
    c_A, c_unknown = arrival_at_cells(oracle, c_flat)
    flats, leaves, arrivals, unknowns = [c_flat], [c_leave], [c_A], [c_unknown]
    kinds, owners = [np.zeros(len(c_flat), np.int8)], [np.full(len(c_flat), -1)]
    edges = np.asarray(path.edges, dtype=np.int64)
    if len(edges):
        table, rg = edge_fire.table, edge_fire.rg
        starts = table.cell_ptr[edges]
        counts = table.cell_ptr[edges + 1] - starts
        idx = np.repeat(starts, counts) + (np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts))
        lengths = rg.edge_len_m[edges]
        edge_start = path.connector_m + np.concatenate([[0.0], np.cumsum(lengths)[:-1]])
        flats.append(table.cell_flat[idx])
        leaves.append(table.cell_leave_m[idx] + np.repeat(edge_start, counts))
        arrivals.append(edge_fire.cell_A[idx])
        unknowns.append(edge_fire.cell_unknown[idx])
        kinds.append(np.ones(len(idx), np.int8))
        owners.append(np.repeat(edges, counts))
    s_flat = np.array([grid.flat_of(*path.shelter_xy)])
    s_A, s_unknown = arrival_at_cells(oracle, s_flat)
    flats.append(s_flat)
    leaves.append(np.array([path.total_m]))
    arrivals.append(s_A)
    unknowns.append(s_unknown)
    kinds.append(np.array([2], np.int8))
    owners.append(np.array([-1]))

    flat = np.concatenate(flats)
    leave_d = np.concatenate(leaves)
    A = np.concatenate(arrivals)
    unknown = np.concatenate(unknowns)
    kind = np.concatenate(kinds)
    owner = np.concatenate(owners)

    t_leave = t_now + leave_d / 1000.0 / SPEED_KM_PER_MIN
    spare = (A - BUFFER_MIN) - t_leave
    finite = np.isfinite(A)
    arrival_sim_min = t_now + path.total_min

    complete = path.access_verified and not bool(unknown.any())
    covers_until = float(oracle.covers_until_sim_min)
    coverage_spare = covers_until - COVERAGE_SLACK_MIN - arrival_sim_min
    if coverage_spare < -EPS_MIN:
        log.warning("route ends at T+%.0f, too close to the forecast window's end (T+%.0f)",
                    arrival_sim_min, covers_until)
        complete = False

    shelter_threat = int(math.floor(s_A[0])) if np.isfinite(s_A[0]) else None
    fire_spare = float(spare[finite].min()) if finite.any() else math.inf
    # A known conflict proves blockage even when other cells are unknown. Lack
    # of coverage alone cannot prove either safety or a fire conflict.
    blocked = fire_spare < -EPS_MIN
    if not blocked and not complete:
        reason = ("Traversable origin, destination, or road-junction access is not established by the map."
                  if not path.access_verified else
                  "Forecast is unavailable or invalid in cells on this route." if unknown.any()
                  else "Forecast ends before the journey and required 90-minute reserve are covered.")
        return indeterminate(path, t_now, reason, shelter_threat)

    limiting_spare = fire_spare if blocked else min(fire_spare, coverage_spare)
    margin = int(math.floor(limiting_spare + EPS_MIN))
    status = "blocked" if blocked else ("tight" if margin < OK_MIN else "ok")
    clear_until = (int(math.floor(min(float(A[finite].min()) - BUFFER_MIN,
                                     covers_until - COVERAGE_SLACK_MIN)))
                   if not blocked and finite.any() else None)

    def place(i):
        if kind[i] == 0:
            return CONNECTOR_NAME, "on the road by your location"
        if kind[i] == 2:
            return path.shelter_name, f"at {path.shelter_name}"
        name = edge_fire.rg.edge_name[owner[i]]
        return name, f"on {name}"

    def intercept(i):
        fire = int(math.floor(A[i]))
        return {
            **_intercept_point(path, edge_fire, grid, int(flat[i]), int(kind[i]), int(owner[i])),
            "road_name": place(i)[0],
            "fire_arrival_sim_min": fire,
            "closes_at_sim_min": fire - BUFFER_MIN,
            "driver_arrival_sim_min": int(math.ceil(t_leave[i] - EPS_MIN)),
            "driver_arrival_is_lower_bound": not path.access_verified,
        }

    reason = hazard = None
    if status == "tight" and coverage_spare < fire_spare:
        reason = "Forecast coverage limits how long departure can be delayed."
    if status == "blocked":
        first = int(np.flatnonzero(spare + EPS_MIN < 0)[0])
        hazard = intercept(first)
        burning = np.flatnonzero(finite & (A <= t_now))
        if len(burning):
            reason = f"Fire is already {place(int(burning[0]))[1]}."
        else:
            reason = (f"Fire is expected {place(first)[1]} at {t_label(hazard['fire_arrival_sim_min'])}. "
                      f"Roads close at {t_label(hazard['closes_at_sim_min'])}; "
                      f"the {'modeled travel lower bound is' if not path.access_verified else 'modeled arrival is'} "
                      f"{t_label(hazard['driver_arrival_sim_min'])}.")
    elif status == "tight" and finite.any() and fire_spare <= coverage_spare:
        hazard = intercept(int(np.argmin(np.where(finite, spare, np.inf))))

    # Compute from unrounded absolute limits so fractional departure times do
    # not introduce extra rounding. Expiry caps every active forecast deadline.
    leave_by = int(math.floor(t_now + min(fire_spare, coverage_spare) + EPS_MIN))
    if not complete:
        leave_by = None
    return Judgement(status, margin, leave_by, clear_until, reason, hazard, shelter_threat,
                     complete, arrival_sim_min)


def t_label(minute: int) -> str:
    return f"T+{minute}" if minute >= 0 else f"T-{-minute}"


def _intercept_point(path, edge_fire, grid, flat, kind, edge) -> dict:
    """The failing cell's centre, snapped onto the road it lies on."""
    if kind == 2 or flat < 0:
        lon, lat = path.shelter_ll if kind == 2 else path.pin_ll
        return {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
    coords = edge_fire.rg.edge_coords_xy(edge) if kind == 1 else np.array([path.pin_xy, path.join_xy])
    centre = Point(grid.centre(flat))
    line = LineString(coords)
    snapped = line.interpolate(line.project(centre)) if line.length > 0 else Point(coords[0])
    lon, lat = TO_LONLAT.transform(snapped.x, snapped.y)
    return {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
