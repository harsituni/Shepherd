"""Fire checks for routing v3: per-road deadlines and the cell-by-cell judge.

The contract's rule: a route is unsafe if the driver leaves any 100 m fire-grid
cell on it later than BUFFER_MIN minutes before the fire's forecast arrival there.

`EdgeFire` reduces every road to one number per forecast version, its deadline:
the latest sim minute a driver may enter it and still clear every cell in time.

    D_e = min_i (A_i - BUFFER_MIN - d_i / v)

A_i is the fire's arrival in the edge's i-th cell, d_i the distance from the edge's
start to where it leaves that cell. Cells the fire doesn't reach within the
forecast window have A = +inf.

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
    unknown = flat < 0
    on_grid = ~unknown
    arrival[on_grid] = oracle.arrival[flat[on_grid]]
    unknown[on_grid] = ~oracle.in_domain[flat[on_grid]]
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
            slack = cell_A - BUFFER_MIN - (table.cell_leave_m / 1000.0) / SPEED_KM_PER_MIN
            deadline = (np.minimum.reduceat(slack, table.cell_ptr[:-1])
                        if len(slack) else np.full(rg.n_edges, np.inf))
            for a in (cell_A, cell_unknown, deadline):
                a.flags.writeable = False
            built = cls(oracle, rg, table, cell_A, cell_unknown, deadline)
            _recent.insert(0, built)
            del _recent[KEEP_VERSIONS:]
            return built


_lock = threading.Lock()
_recent: list = []


def _cached(rg, table, oracle):
    for fire in list(_recent):
        if fire.rg is rg and fire.table is table and fire.oracle.version == oracle.version:
            return fire
    return None


@dataclass(frozen=True, eq=False)
class RoutePath:
    """One way out: pin -> straight connector -> road edges -> the shelter's road point.

    For a straight-line estimate (no road graph), the connector runs all the way to
    the shelter and `edges` is empty.
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
    status: str                         # ok | tight | blocked
    margin_min: Optional[int]
    leave_by_sim_min: Optional[int]
    clear_until_sim_min: Optional[int]
    reason: Optional[str]
    hazard_intercept: Optional[dict]
    shelter_threat_sim_min: Optional[int]
    forecast_complete: bool
    arrival_sim_min: float              # when the driver reaches the shelter's road point


def clear(path: RoutePath, t_now: float) -> Judgement:
    """No fire running: every route is ok with no margin."""
    return Judgement("ok", None, None, None, None, None, None, True, t_now + path.total_min)


def judge(path: RoutePath, t_now: float, oracle=None, edge_fire: Optional[EdgeFire] = None) -> Judgement:
    """Check every cell on the route against the 30-minute rule."""
    if oracle is None:
        return clear(path, t_now)
    if len(path.edges) and edge_fire is None:
        raise ValueError("a road route needs the EdgeFire for its forecast")
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

    complete = not bool(unknown.any())
    covers_until = float(getattr(oracle, "covers_until_sim_min", math.inf))
    if arrival_sim_min > covers_until - COVERAGE_SLACK_MIN:
        log.warning("route ends at T+%.0f, too close to the forecast window's end (T+%.0f)",
                    arrival_sim_min, covers_until)
        complete = False

    shelter_threat = int(math.floor(s_A[0])) if np.isfinite(s_A[0]) else None
    if not finite.any():
        return Judgement("ok", None, None, None, None, None, shelter_threat, complete, arrival_sim_min)

    margin = int(math.floor(float(spare[finite].min()) + EPS_MIN))
    status = "blocked" if margin < 0 else ("tight" if margin < OK_MIN else "ok")
    clear_until = None if status == "blocked" else int(math.floor(float(A[finite].min()))) - BUFFER_MIN

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
        }

    reason = hazard = None
    if status == "blocked":
        first = int(np.flatnonzero(spare + EPS_MIN < 0)[0])
        hazard = intercept(first)
        burning = np.flatnonzero(finite & (A <= t_now))
        if len(burning):
            reason = f"Fire is already {place(int(burning[0]))[1]}."
        else:
            reason = (f"Fire is expected {place(first)[1]} at {t_label(hazard['fire_arrival_sim_min'])}. "
                      f"Roads close at {t_label(hazard['closes_at_sim_min'])}; "
                      f"you would reach it at {t_label(hazard['driver_arrival_sim_min'])}.")
    elif status == "tight":
        hazard = intercept(int(np.argmin(np.where(finite, spare, np.inf))))

    leave_by = int(math.floor(t_now + margin))
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
