"""Test helpers for routing v3: tiny road networks and hand-made forecasts.

Not used by the app. Roads are laid out in metres east/north of a point in
south-west Edmonton (inside the demo area), and forecasts are ForecastOracles
whose arrival grid the test fills cell by cell.
"""

from __future__ import annotations

import itertools
import math

import networkx as nx
import numpy as np
from shapely.geometry import LineString

from backend.routing.road_graph import TO_GRID, TO_LONLAT, FireGrid, traverse_segment
from backend.sim.oracle import ForecastOracle

ORIGIN_LL = (-113.55, 53.50)
ORIGIN_XY = TO_GRID.transform(*ORIGIN_LL)
_VERSIONS = itertools.count(10_000_000)


def ll(east_m: float, north_m: float) -> tuple:
    """(lon, lat) of a point this many metres from the origin."""
    lon, lat = TO_LONLAT.transform(ORIGIN_XY[0] + east_m, ORIGIN_XY[1] + north_m)
    return float(lon), float(lat)


def local_graph(nodes: dict, edges: list, crs="EPSG:4326") -> nx.MultiDiGraph:
    """nodes: {id: (east_m, north_m)}; edges: [(u, v, length_m)] one-way, straight geometry."""
    graph = nx.MultiDiGraph(crs=crs)
    for node, (e, n) in nodes.items():
        lon, lat = ll(e, n)
        graph.add_node(node, x=lon, y=lat)
    for u, v, length in edges:
        geometry = LineString([ll(*nodes[u]), ll(*nodes[v])])
        graph.add_edge(u, v, length=float(length), geometry=geometry, name=f"{u}-{v} Road")
    return graph


def shelter(name: str, lonlat: tuple, is_open=True, capacity=100, occupancy=0) -> dict:
    return {
        "type": "Feature", "id": name,
        "properties": {"name": name, "open": is_open, "capacity": capacity, "occupancy": occupancy},
        "geometry": {"type": "Point", "coordinates": [lonlat[0], lonlat[1]]},
    }


def grid_around(lonlats, margin_m=1500.0, cell_m=100.0) -> FireGrid:
    """A fire grid covering the points, its origin on a multiple of cell_m like the engine's."""
    xs, ys = TO_GRID.transform([p[0] for p in lonlats], [p[1] for p in lonlats])
    x0 = math.floor((min(xs) - margin_m) / cell_m) * cell_m
    y0 = math.ceil((max(ys) + margin_m) / cell_m) * cell_m
    ncols = int(math.ceil((max(xs) + margin_m - x0) / cell_m))
    nrows = int(math.ceil((y0 - (min(ys) - margin_m)) / cell_m))
    return FireGrid(float(x0), float(y0), float(cell_m), nrows, ncols)


class Forecast:
    """A writable arrival grid that turns into ForecastOracles."""

    def __init__(self, grid: FireGrid, fill=np.inf):
        self.grid = grid
        self.arrival = np.full(grid.nrows * grid.ncols, float(fill))

    def cell(self, lonlat) -> int:
        x, y = TO_GRID.transform(*lonlat)
        return self.grid.flat_of(x, y)

    def at_point(self, lonlat, minute: float) -> int:
        flat = self.cell(lonlat)
        self.arrival[flat] = minute
        return flat

    def along(self, a_ll, b_ll, minute: float) -> np.ndarray:
        """Every cell a straight line from a to b touches."""
        flat, _, _ = traverse_segment(TO_GRID.transform(*a_ll), TO_GRID.transform(*b_ll), self.grid)
        flat = flat[flat >= 0]
        self.arrival[flat] = minute
        return flat

    def where(self, fn) -> None:
        """Set each cell from fn(lat, lon) at its centre; None means not reached."""
        for flat in range(len(self.arrival)):
            lon, lat = TO_LONLAT.transform(*self.grid.centre(flat))
            minute = fn(lat, lon)
            self.arrival[flat] = np.inf if minute is None else float(minute)

    def oracle(self, sim_time: int = 0, covers_until: float = 100_000.0, in_domain=None) -> ForecastOracle:
        arrival = self.arrival.copy()
        arrival.flags.writeable = False
        if in_domain is None:
            in_domain = np.ones(len(arrival), bool)
        return ForecastOracle(
            version=next(_VERSIONS), run_id="test", band="p50", sim_time=sim_time,
            covers_until_sim_min=covers_until, wind_kmh=20.0, wind_from_deg=270.0,
            x0=self.grid.x0, y0=self.grid.y0, cell_m=self.grid.cell_m,
            nrows=self.grid.nrows, ncols=self.grid.ncols, arrival=arrival, in_domain=in_domain,
        )
