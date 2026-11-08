"""Array form of the road graph for routing v3, plus the road-to-fire-cell table.

`RoadGraph.from_networkx()` runs once inside `load_graph()`. Nothing in it changes
afterwards, so request threads share it without locks.

- Nodes: OSM ids, lon/lat, and x/y in UTM zone 12N metres (the fire grid's CRS).
- Edges: one per directed (u, v), the shortest of any parallel roads, sorted by
  u * N + v. One-way roads stay one-way. Self-loops are dropped: they are never
  on a shortest path.
- `csr_time`: travel minutes at SPEED_KM_PER_MIN as a SciPy CSR matrix, for
  `scipy.sparse.csgraph.dijkstra(..., directed=True)`.
- `nearest_node()`: a cKDTree on node x/y.

`build_cell_table()` lists, for every edge, each 100 m fire-grid cell the road
passes through in travel order, with the distances at which it enters and leaves
that cell. A cell counts when the closed road segment meets the closed cell
square, so a road through a cell corner lists all four cells around it and a
road running exactly along a cell border lists the cells on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

SPEED_KM_PER_MIN = 0.5
GRID_CRS = "EPSG:32612"  # UTM zone 12N, the same CRS as the fire grid
MIN_WEIGHT_MIN = 1e-6    # csr_matrix drops nothing, but a zero weight would read as "no edge"
ON_BORDER = 1e-9         # grid units: closer than this to a cell border counts as on it

TO_GRID = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
TO_LONLAT = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)


def road_name(edge: dict) -> str:
    """Display name for an OSM edge: its name, else its road class."""
    name = edge.get("name")
    if isinstance(name, list):
        name = next((part for part in name if part), None)
    if name:
        return str(name)
    highway = edge.get("highway")
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    if highway:
        return str(highway).replace("_", " ")
    return "Unnamed road"


def masked_csr(n: int, edge_u: np.ndarray, edge_v: np.ndarray, weights: np.ndarray,
               allowed: Optional[np.ndarray] = None) -> csr_matrix:
    """CSR matrix of `weights` on the allowed edges.

    Edges must already be sorted by (u, v) with no duplicates: the matrix is built
    straight from indptr/indices, never through COO, which would add duplicates.
    """
    if allowed is not None:
        edge_u, edge_v, weights = edge_u[allowed], edge_v[allowed], weights[allowed]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(edge_u, minlength=n), out=indptr[1:])
    return csr_matrix((np.maximum(weights, MIN_WEIGHT_MIN), edge_v, indptr), shape=(n, n))


@dataclass(frozen=True, eq=False)
class RoadGraph:
    node_osmid: np.ndarray
    node_lon: np.ndarray
    node_lat: np.ndarray
    node_x: np.ndarray
    node_y: np.ndarray
    edge_u: np.ndarray        # (E,) node index
    edge_v: np.ndarray        # (E,) node index
    edge_key: np.ndarray      # (E,) u * N + v, sorted
    edge_len_m: np.ndarray
    edge_time_min: np.ndarray
    edge_name: tuple
    geom_ptr: np.ndarray      # (E+1,) slices into the geom_* arrays, in travel order
    geom_lon: np.ndarray
    geom_lat: np.ndarray
    geom_x: np.ndarray
    geom_y: np.ndarray
    csr_time: csr_matrix
    bbox: tuple               # (min_lon, min_lat, max_lon, max_lat) over every road point
    tree: cKDTree
    osmid_index: dict

    @property
    def n_nodes(self) -> int:
        return len(self.node_osmid)

    @property
    def n_edges(self) -> int:
        return len(self.edge_u)

    @property
    def edge_weight(self) -> np.ndarray:
        """Travel minutes as stored in csr_time (never zero)."""
        return np.maximum(self.edge_time_min, MIN_WEIGHT_MIN)

    @classmethod
    def from_networkx(cls, graph) -> "RoadGraph":
        osmids = list(graph.nodes)
        n = len(osmids)
        index = {osmid: i for i, osmid in enumerate(osmids)}
        node_lon = np.array([float(graph.nodes[o]["x"]) for o in osmids], dtype=float)
        node_lat = np.array([float(graph.nodes[o]["y"]) for o in osmids], dtype=float)
        node_x, node_y = (np.asarray(a, dtype=float) for a in TO_GRID.transform(node_lon, node_lat))

        # Parallel roads: keep the shortest per (u, v).
        best = {}
        for u, v, data in graph.edges(data=True):
            if u == v:
                continue
            key = (index[u], index[v])
            length = float(data.get("length", 0.0))
            if key not in best or length < best[key][0]:
                best[key] = (length, data)
        pairs = sorted(best, key=lambda uv: uv[0] * n + uv[1])
        edge_u = np.array([u for u, _ in pairs], dtype=np.int32)
        edge_v = np.array([v for _, v in pairs], dtype=np.int32)
        edge_len_m = np.array([best[p][0] for p in pairs], dtype=float)

        names, lons, lats, counts = [], [], [], []
        for (u, v) in pairs:
            data = best[(u, v)][1]
            names.append(road_name(data))
            coords = _travel_coords(data.get("geometry"), (node_lon[u], node_lat[u]),
                                    (node_lon[v], node_lat[v]))
            lons.extend(c[0] for c in coords)
            lats.extend(c[1] for c in coords)
            counts.append(len(coords))
        geom_ptr = np.zeros(len(pairs) + 1, dtype=np.int64)
        np.cumsum(counts, out=geom_ptr[1:])
        geom_lon = np.array(lons, dtype=float)
        geom_lat = np.array(lats, dtype=float)
        if len(geom_lon):
            geom_x, geom_y = (np.asarray(a, dtype=float) for a in TO_GRID.transform(geom_lon, geom_lat))
            all_lon = np.concatenate([node_lon, geom_lon])
            all_lat = np.concatenate([node_lat, geom_lat])
        else:
            geom_x = geom_y = np.zeros(0)
            all_lon, all_lat = node_lon, node_lat
        bbox = ((float(all_lon.min()), float(all_lat.min()), float(all_lon.max()), float(all_lat.max()))
                if n else (0.0, 0.0, 0.0, 0.0))

        edge_time_min = edge_len_m / 1000.0 / SPEED_KM_PER_MIN
        return cls(
            node_osmid=np.array(osmids, dtype=object),
            node_lon=node_lon, node_lat=node_lat, node_x=node_x, node_y=node_y,
            edge_u=edge_u, edge_v=edge_v,
            edge_key=edge_u.astype(np.int64) * n + edge_v,
            edge_len_m=edge_len_m, edge_time_min=edge_time_min,
            edge_name=tuple(names),
            geom_ptr=geom_ptr, geom_lon=geom_lon, geom_lat=geom_lat, geom_x=geom_x, geom_y=geom_y,
            csr_time=masked_csr(n, edge_u, edge_v, edge_time_min),
            bbox=bbox,
            tree=cKDTree(np.column_stack([node_x, node_y])) if n else None,
            osmid_index=index,
        )

    # ---------- lookups ----------

    def nearest_node(self, lat: float, lon: float) -> tuple:
        """(node index, distance in metres) of the road node nearest the point."""
        x, y = TO_GRID.transform(lon, lat)
        dist, idx = self.tree.query([x, y])
        return int(idx), float(dist)

    def node_index(self, osmid) -> int:
        return self.osmid_index[osmid]

    def edge_index(self, u, v) -> np.ndarray:
        """Edge indices for node index pairs (arrays or scalars). Every pair must exist."""
        keys = np.asarray(u, dtype=np.int64) * self.n_nodes + np.asarray(v, dtype=np.int64)
        found = np.searchsorted(self.edge_key, keys)
        if np.any(found >= len(self.edge_key)) or np.any(self.edge_key[np.minimum(found, len(self.edge_key) - 1)] != keys):
            raise KeyError("no edge for some (u, v) pair")
        return found

    def path_edges(self, nodes) -> np.ndarray:
        """Edge indices along a node path."""
        nodes = np.asarray(nodes, dtype=np.int64)
        if len(nodes) < 2:
            return np.zeros(0, dtype=np.int64)
        return self.edge_index(nodes[:-1], nodes[1:]).astype(np.int64)

    def masked_csr(self, weights: np.ndarray, allowed: Optional[np.ndarray] = None) -> csr_matrix:
        return masked_csr(self.n_nodes, self.edge_u, self.edge_v, weights, allowed)

    def edge_coords_ll(self, e: int) -> np.ndarray:
        s, t = self.geom_ptr[e], self.geom_ptr[e + 1]
        return np.column_stack([self.geom_lon[s:t], self.geom_lat[s:t]])

    def edge_coords_xy(self, e: int) -> np.ndarray:
        s, t = self.geom_ptr[e], self.geom_ptr[e + 1]
        return np.column_stack([self.geom_x[s:t], self.geom_y[s:t]])


def _travel_coords(geometry, start, end) -> list:
    """The road's points from u to v. Stored geometry may run either way."""
    if geometry is None:
        return [start, end]
    coords = [(float(x), float(y)) for x, y in geometry.coords]
    if len(coords) < 2:
        return [start, end]
    first = (coords[0][0] - start[0]) ** 2 + (coords[0][1] - start[1]) ** 2
    last = (coords[-1][0] - start[0]) ** 2 + (coords[-1][1] - start[1]) ** 2
    if last < first:
        coords.reverse()
    return coords


# ---------- fire grid cells ----------

@dataclass(frozen=True)
class FireGrid:
    """The fire grid: x0/y0 is the outer top-left corner; row 0 is the northernmost."""
    x0: float
    y0: float
    cell_m: float
    nrows: int
    ncols: int

    @classmethod
    def of(cls, oracle) -> "FireGrid":
        return cls(float(oracle.x0), float(oracle.y0), float(oracle.cell_m), int(oracle.nrows), int(oracle.ncols))

    def flat_of(self, x: float, y: float) -> int:
        """Cell containing one point, or -1 off the grid."""
        col = int(np.floor((x - self.x0) / self.cell_m))
        row = int(np.floor((self.y0 - y) / self.cell_m))
        if 0 <= row < self.nrows and 0 <= col < self.ncols:
            return row * self.ncols + col
        return -1

    def centre(self, flat: int) -> tuple:
        row, col = divmod(int(flat), self.ncols)
        return self.x0 + (col + 0.5) * self.cell_m, self.y0 - (row + 0.5) * self.cell_m


def _cells_at(gx: np.ndarray, gy: np.ndarray, grid: FireGrid):
    """Every cell whose closed square holds each point (1, 2 or 4 cells).

    Returns (point index, flat cell) pairs; flat is -1 off the grid.
    """
    rx, ry = np.rint(gx), np.rint(gy)
    on_x = np.abs(gx - rx) < ON_BORDER
    on_y = np.abs(gy - ry) < ON_BORDER
    col = np.where(on_x, rx - 1, np.floor(gx)).astype(np.int64)
    row = np.where(on_y, ry - 1, np.floor(gy)).astype(np.int64)
    point = np.arange(len(gx))
    pts, rows, cols = [point], [row], [col]
    for extra_col, extra_row, mask in ((1, 0, on_x), (0, 1, on_y), (1, 1, on_x & on_y)):
        pts.append(point[mask])
        rows.append(row[mask] + extra_row)
        cols.append(col[mask] + extra_col)
    pts, rows, cols = np.concatenate(pts), np.concatenate(rows), np.concatenate(cols)
    inside = (rows >= 0) & (rows < grid.nrows) & (cols >= 0) & (cols < grid.ncols)
    return pts, np.where(inside, rows * grid.ncols + cols, -1)


def traverse(x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray, grid: FireGrid):
    """Cells touched by each segment, in travel order (Amanatides-Woo style, vectorised).

    Inputs are (S,) arrays of segment endpoints in grid-CRS metres. Returns
    (segment, flat cell, t_enter, t_leave), sorted by segment then t, where t is the
    fraction along the segment. Every border crossing splits the segment into
    pieces that lie in one cell each; corner crossings and endpoints that sit on
    a border also list the cells they only touch.
    """
    x0, y0, x1, y1 = (np.atleast_1d(np.asarray(a, dtype=float)) for a in (x0, y0, x1, y1))
    gx0, gx1 = (x0 - grid.x0) / grid.cell_m, (x1 - grid.x0) / grid.cell_m
    gy0, gy1 = (grid.y0 - y0) / grid.cell_m, (grid.y0 - y1) / grid.cell_m
    seg = np.arange(len(gx0))

    # Event points: both ends of every segment, then every border it crosses.
    ev_seg, ev_t, ev_gx, ev_gy = [seg, seg], [np.zeros(len(seg)), np.ones(len(seg))], [gx0, gx1], [gy0, gy1]
    ev_end = [np.ones(len(seg), bool), np.ones(len(seg), bool)]
    for a0, a1, b0, b1, a_is_x in ((gx0, gx1, gy0, gy1, True), (gy0, gy1, gx0, gx1, False)):
        first = np.floor(np.minimum(a0, a1)) + 1
        count = np.clip(np.ceil(np.maximum(a0, a1)) - first, 0, None).astype(np.int64)
        total = int(count.sum())
        if not total:
            continue
        which = np.repeat(seg, count)
        k = np.repeat(first, count) + (np.arange(total) - np.repeat(np.cumsum(count) - count, count))
        t = (k - a0[which]) / (a1 - a0)[which]
        other = b0[which] + t * (b1 - b0)[which]
        ev_seg.append(which)
        ev_t.append(t)
        ev_gx.append(k if a_is_x else other)
        ev_gy.append(other if a_is_x else k)
        ev_end.append(np.zeros(total, bool))
    ev_seg, ev_t = np.concatenate(ev_seg), np.concatenate(ev_t)
    ev_gx, ev_gy, ev_end = np.concatenate(ev_gx), np.concatenate(ev_gy), np.concatenate(ev_end)
    order = np.lexsort((ev_t, ev_seg))
    ev_seg, ev_t, ev_gx, ev_gy, ev_end = ev_seg[order], ev_t[order], ev_gx[order], ev_gy[order], ev_end[order]

    # Pieces between consecutive events lie inside one cell (two along a border).
    piece = (ev_seg[1:] == ev_seg[:-1]) & (ev_t[1:] > ev_t[:-1])
    p_seg, p_t0, p_t1 = ev_seg[:-1][piece], ev_t[:-1][piece], ev_t[1:][piece]
    tm = (p_t0 + p_t1) / 2
    mid_gx = gx0[p_seg] + tm * (gx1 - gx0)[p_seg]
    mid_gy = gy0[p_seg] + tm * (gy1 - gy0)[p_seg]
    # A zero-length segment has no piece with length; its t=0 and t=1 events coincide.
    lone = np.ones(len(seg), bool)
    lone[p_seg] = False
    p_seg = np.concatenate([p_seg, seg[lone]])
    p_t0 = np.concatenate([p_t0, np.zeros(int(lone.sum()))])
    p_t1 = np.concatenate([p_t1, np.zeros(int(lone.sum()))])
    mid_gx = np.concatenate([mid_gx, gx0[lone]])
    mid_gy = np.concatenate([mid_gy, gy0[lone]])
    pi, pflat = _cells_at(mid_gx, mid_gy, grid)

    # Points that only touch extra cells: corners, and segment ends on a border.
    on_x = np.abs(ev_gx - np.rint(ev_gx)) < ON_BORDER
    on_y = np.abs(ev_gy - np.rint(ev_gy)) < ON_BORDER
    touch = (on_x & on_y) | (ev_end & (on_x | on_y))
    ei, eflat = _cells_at(ev_gx[touch], ev_gy[touch], grid)
    t_touch = ev_t[touch]

    out_seg = np.concatenate([p_seg[pi], ev_seg[touch][ei]])
    out_flat = np.concatenate([pflat, eflat])
    out_t0 = np.concatenate([p_t0[pi], t_touch[ei]])
    out_t1 = np.concatenate([p_t1[pi], t_touch[ei]])
    order = np.lexsort((out_t1, out_t0, out_seg))
    return out_seg[order], out_flat[order], out_t0[order], out_t1[order]


def _merge_repeats(group, flat, enter, leave):
    """Merge consecutive entries for the same cell in the same group."""
    if len(group) == 0:
        return group, flat, enter, leave
    new = np.ones(len(group), bool)
    new[1:] = (group[1:] != group[:-1]) | (flat[1:] != flat[:-1])
    starts = np.flatnonzero(new)
    return group[starts], flat[starts], enter[starts], np.maximum.reduceat(leave, starts)


def traverse_segment(xy0, xy1, grid: FireGrid):
    """(flat cells, enter_m, leave_m) along one straight segment, e.g. the pin-to-road connector."""
    seg, flat, t0, t1 = traverse([xy0[0]], [xy0[1]], [xy1[0]], [xy1[1]], grid)
    length = float(np.hypot(xy1[0] - xy0[0], xy1[1] - xy0[1]))
    _, flat, enter, leave = _merge_repeats(seg, flat, t0 * length, t1 * length)
    return flat, enter, leave


@dataclass(frozen=True, eq=False)
class CellTable:
    grid: FireGrid
    cell_ptr: np.ndarray      # (E+1,) slices into the arrays below
    cell_flat: np.ndarray     # row * ncols + col, -1 off the grid
    cell_enter_m: np.ndarray  # distance from the edge's start to where it enters the cell
    cell_leave_m: np.ndarray  # ... and where it leaves it


def build_cell_table(rg: RoadGraph, grid: FireGrid) -> CellTable:
    """Cells crossed by every edge, in travel order.

    Distances are scaled so each edge's last cell leaves at exactly its OSM length,
    which keeps cell times consistent with the edge travel times used in search.
    """
    n_points = len(rg.geom_x)
    n_edges = rg.n_edges
    point_edge = np.repeat(np.arange(n_edges), np.diff(rg.geom_ptr))
    # Segment i joins point i to i + 1 when both belong to the same edge.
    starts = np.arange(max(n_points - 1, 0))
    starts = starts[point_edge[starts] == point_edge[starts + 1]] if n_points > 1 else starts
    seg_edge = point_edge[starts]
    sx0, sy0 = rg.geom_x[starts], rg.geom_y[starts]
    sx1, sy1 = rg.geom_x[starts + 1], rg.geom_y[starts + 1]
    seg_len = np.hypot(sx1 - sx0, sy1 - sy0)
    poly_len = np.bincount(seg_edge, weights=seg_len, minlength=n_edges)
    before = np.cumsum(seg_len) - seg_len
    first_seg = np.searchsorted(seg_edge, np.arange(n_edges))
    seg_offset = before - before[np.minimum(first_seg, len(before) - 1)][seg_edge] if len(before) else before
    scale = np.where(poly_len > 0, rg.edge_len_m / np.where(poly_len > 0, poly_len, 1.0), 1.0)

    seg, flat, t0, t1 = traverse(sx0, sy0, sx1, sy1, grid)
    edge = seg_edge[seg]
    enter = (seg_offset[seg] + t0 * seg_len[seg]) * scale[edge]
    leave = (seg_offset[seg] + t1 * seg_len[seg]) * scale[edge]
    # Two distinct nodes at the same spot: the whole length is spent in one cell.
    leave = np.where(poly_len[edge] > 0, leave, rg.edge_len_m[edge])
    edge, flat, enter, leave = _merge_repeats(edge, flat, enter, leave)

    cell_ptr = np.zeros(n_edges + 1, dtype=np.int64)
    np.cumsum(np.bincount(edge, minlength=n_edges), out=cell_ptr[1:])
    return CellTable(grid=grid, cell_ptr=cell_ptr, cell_flat=flat.astype(np.int64),
                     cell_enter_m=enter, cell_leave_m=leave)
