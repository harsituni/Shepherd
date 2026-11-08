"""Request-local directed edge access. Proximity is not proof of traversability.

Only points on mapped public road geometry are supported without additional
access data. Off-road gaps are retained as explicitly unmodeled portions, never
as straight traversable connectors. No shared graph or forecast is modified.

Demo simplification: a journey may start at the person's nearest road point
(`road_start`) and end at a shelter's designated road point. The gaps to the
actual person and building are reported, never driven, drawn or timed.
"""
import weakref
from dataclasses import dataclass, replace

import networkx as nx
import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components
from shapely.geometry import Point, box
from shapely.ops import substring

from backend.routing.road_graph import TO_GRID, TO_LONLAT, CellTable, SPEED_KM_PER_MIN, traverse_segment
from backend.routing.safety import BUFFER_MIN, EdgeFire, arrival_at_cells

ACCESS_RADIUS_M = 300.
ON_ROAD_M = .001  # numerical coordinate tolerance, not a GPS/accessibility allowance
AMBIGUOUS = "Ambiguous crossing without a mapped junction"
ROAD_START = "Journey starts at the nearest road point; access from your location unverified"


@dataclass(frozen=True)
class Snap:
    edge: int
    fraction: float
    ll: tuple
    gap_m: float
    verified: bool
    reason: str

    def describe(self, point):
        return {"status": "mapped" if self.verified else "unverified",
                "point": list(point), "road_point": list(self.ll),
                "gap_m": float(self.gap_m), "reason": self.reason}


def snaps(rg, lon, lat, *, destination=False):
    point = Point(TO_GRID.transform(lon, lat))
    x, y = point.x, point.y
    ids = rg.edge_tree.query(box(x-ACCESS_RADIUS_M-1e-7, y-ACCESS_RADIUS_M-1e-7,
                                 x+ACCESS_RADIUS_M+1e-7, y+ACCESS_RADIUS_M+1e-7))
    ids = ids[rg.edge_permitted[ids]]
    dist = shapely.distance(rg.edge_lines[ids], point)
    ids = ids[dist <= ACCESS_RADIUS_M + 1e-8]
    # A far shelter remains explicitly unsupported, rather than pretending it
    # is reached at its nearest junction. Only a diagnostic road endpoint is used.
    if not len(ids) and destination:
        permitted = np.flatnonzero(rg.edge_permitted)
        if len(permitted):
            d = shapely.distance(rg.edge_lines[permitted], point)
            ids = permitted[np.isclose(d, d.min(), rtol=0, atol=ON_ROAD_M)]
    found = []
    for e in sorted(map(int, ids)):
        line = rg.edge_lines[e]
        at = line.project(point)
        p = line.interpolate(at)
        gap = point.distance(p)
        verified = gap <= ON_ROAD_M and line.is_simple
        found.append(Snap(e, at/line.length if line.length else 0.,
                          tuple(map(float, TO_LONLAT.transform(p.x, p.y))), gap, verified,
                          "On mapped road geometry" if verified else "No mapped traversable access connection"))
    # An on-road pin already identifies its mapped corridor(s). Nearby but
    # off-road candidates must not create shortcuts away from that known road.
    if any(s.verified for s in found):
        found = [s for s in found if s.verified]
    if _ambiguous(rg, [s for s in found if s.verified]):
        found = [replace(s, verified=False, reason=AMBIGUOUS) if s.verified else s for s in found]
    return found


def _ambiguous(rg, at_point):
    """Distinct crossing corridors without a graph junction cannot be selected
    from a 2D pin alone (e.g. bridge over a road). Do not invent a transfer."""
    junctions = nx.Graph()
    groups = set()
    for s in at_point:
        u, v = int(rg.edge_u[s.edge]), int(rg.edge_v[s.edge])
        line = rg.edge_lines[s.edge]
        if line.length <= ON_ROAD_M:
            junctions.add_edge(u, v)
        elif s.fraction * line.length <= ON_ROAD_M:
            junctions.add_node(u)
        elif (1-s.fraction) * line.length <= ON_ROAD_M:
            junctions.add_node(v)
        else:
            groups.add((min(u, v), max(u, v), shapely.normalize(line).wkb))
    return len(groups) + nx.number_connected_components(junctions) > 1


def road_start(rg, lon, lat):
    """Possible journey starts, best first; each is the origin snaps for one point.

    An on-road pin keeps its mapped corridor(s), or stays ambiguous at a crossing.
    Otherwise each start is one road point within 300 m, with every directed road
    through it, so a two-way street or junction keeps all its directions. Points
    whose roads lead onto the main road network come first, then by distance. The
    gap from the person to the point is reported as `gap_m`, never driven, drawn
    or timed. The caller uses the first start from which a shelter is reachable.
    """
    found = snaps(rg, lon, lat)
    if not found or any(s.gap_m <= ON_ROAD_M for s in found):
        return [found] if found else []
    joins = _joins_network(rg)
    leads_on = rg.edge_permitted & _meets_node(rg, end=True)
    found = sorted(found, key=lambda s: (s.gap_m, s.edge))
    edges = np.array([s.edge for s in found])
    at = shapely.get_coordinates(shapely.line_interpolate_point(
        rg.edge_lines[edges], [s.fraction for s in found], normalized=True))
    starts, placed = [], np.zeros(len(found), bool)
    for i in range(len(found)):
        if placed[i]:
            continue
        members = np.flatnonzero(~placed & (np.hypot(*(at - at[i]).T) <= ON_ROAD_M))
        placed[members] = True
        group = [found[k] for k in members]
        on_network = bool((leads_on[edges[members]] & joins[rg.edge_v[edges[members]]]).any())
        if _ambiguous(rg, group):
            group = [replace(s, reason=AMBIGUOUS) for s in group]
        else:
            group = [replace(s, verified=True, reason=ROAD_START) for s in group]
        starts.append((not on_network, len(starts), group))
    return [group for _, _, group in sorted(starts, key=lambda t: t[:2])]


_networks = weakref.WeakKeyDictionary()


def _meets_node(rg, end):
    """Per edge: its geometry starts (or ends) on its graph node."""
    p = rg.geom_ptr[1:] - 1 if end else rg.geom_ptr[:-1]
    node = rg.edge_v if end else rg.edge_u
    return np.hypot(rg.geom_x[p] - rg.node_x[node], rg.geom_y[p] - rg.node_y[node]) <= ON_ROAD_M


def _joins_network(rg):
    """Per node: can drive onto the main road network, the largest strongly connected
    part of the map when it holds most nodes. Without one, every node qualifies."""
    hit = _networks.get(rg)
    if hit is None:
        ok = rg.edge_permitted & _meets_node(rg, end=False) & _meets_node(rg, end=True)
        graph = coo_matrix((np.ones(int(ok.sum())), (rg.edge_u[ok], rg.edge_v[ok])),
                           shape=(rg.n_nodes, rg.n_nodes)).tocsr()
        _, labels = connected_components(graph, directed=True, connection="strong")
        sizes = np.bincount(labels)
        hit = np.ones(rg.n_nodes, bool)
        if 2 * sizes.max() > rg.n_nodes:
            seed = int(np.argmax(labels == np.argmax(sizes)))
            hit[:] = False
            hit[breadth_first_order(graph.T.tocsr(), seed, directed=True, return_predecessors=False)] = True
        _networks[rg] = hit
    return hit


class JourneyGraph:
    """Base road edges plus directed origin suffixes/destination prefixes.

    Original keyed edges remain distinct. Same-edge origin/destination pairs
    receive a direct clipped arc only in the allowed direction. Arc geometry
    never contains an unverified off-road gap; access records describe that gap.
    """
    def __init__(self, base, origin, shelters, origin_snaps, destination_snaps):
        self.base = base
        self.start = base.n_nodes
        self.targets = {s["id"]: base.n_nodes + 1 + i for i, s in enumerate(shelters)}
        self.n_nodes = base.n_nodes + 1 + len(shelters)
        self.origin = origin
        self.origins, self.destinations = {}, {}
        extra = []
        for snap in origin_snaps:
            extra.append((self.start, int(base.edge_v[snap.edge]), snap.edge,
                          snap.fraction, 1., snap.describe(origin), None))
        for s in shelters:
            target = self.targets[s["id"]]
            point = tuple(s["geometry"]["coordinates"])
            for end in destination_snaps[s["id"]]:
                extra.append((int(base.edge_u[end.edge]), target, end.edge,
                              0., end.fraction, None, end.describe(point)))
                for begin in origin_snaps:
                    if begin.edge == end.edge and begin.fraction <= end.fraction + 1e-12:
                        extra.append((self.start, target, end.edge, begin.fraction,
                                      max(begin.fraction, end.fraction), begin.describe(origin), end.describe(point)))
        ecount = base.n_edges
        self.parent = np.r_[np.arange(ecount), [e[2] for e in extra]].astype(int)
        self.frac0 = np.r_[np.zeros(ecount), [e[3] for e in extra]]
        self.frac1 = np.r_[np.ones(ecount), [e[4] for e in extra]]
        u = np.r_[base.edge_u, [e[0] for e in extra]].astype(int)
        v = np.r_[base.edge_v, [e[1] for e in extra]].astype(int)
        order = np.lexsort((np.arange(len(u)), v, u))
        self.edge_u, self.edge_v = u[order], v[order]
        self.parent, self.frac0, self.frac1 = self.parent[order], self.frac0[order], self.frac1[order]
        self.edge_len_m = base.edge_len_m[self.parent] * (self.frac1 - self.frac0)
        self.edge_weight = self.edge_len_m / 1000 / SPEED_KM_PER_MIN
        self.edge_name = tuple(base.edge_name[e] for e in self.parent)
        self.n_edges = len(order)
        self.edge_permitted = base.edge_permitted[self.parent]
        # A geometry endpoint must actually meet the graph node it connects to.
        p0, p1 = base.geom_ptr[self.parent], base.geom_ptr[self.parent + 1] - 1
        at_start = np.hypot(base.geom_x[p0] - base.node_x[base.edge_u[self.parent]],
                            base.geom_y[p0] - base.node_y[base.edge_u[self.parent]]) <= ON_ROAD_M
        at_end = np.hypot(base.geom_x[p1] - base.node_x[base.edge_v[self.parent]],
                          base.geom_y[p1] - base.node_y[base.edge_v[self.parent]]) <= ON_ROAD_M
        self.edge_verified = ((self.edge_u == self.start) | at_start) & (
            (self.edge_v >= base.n_nodes + 1) | at_end)
        self._xy = {}
        self._ll = {}
        for e, old in enumerate(order):
            if old < ecount:
                continue
            record = extra[old-ecount]
            for dest, value in ((self.origins, record[5]), (self.destinations, record[6])):
                if value is not None:
                    dest[e] = value
                    self.edge_verified[e] &= value["status"] == "mapped"

    def edge_coords_xy(self, edge):
        if edge not in self._xy:
            parent = self.parent[edge]
            if self.frac0[edge] == 0 and self.frac1[edge] == 1:
                return self.base.edge_coords_xy(int(parent))
            line = self.base.edge_lines[parent]
            part = substring(line, self.frac0[edge]*line.length, self.frac1[edge]*line.length)
            xy = np.array(part.coords)
            self._xy[edge] = xy if len(xy) > 1 else np.repeat(xy, 2, axis=0)
        return self._xy[edge]

    def edge_coords_ll(self, edge):
        if edge not in self._ll:
            if self.frac0[edge] == 0 and self.frac1[edge] == 1:
                self._ll[edge] = self.base.edge_coords_ll(int(self.parent[edge]))
            else:
                xy = self.edge_coords_xy(edge)
                self._ll[edge] = np.column_stack(TO_LONLAT.transform(xy[:, 0], xy[:, 1]))
        return self._ll[edge]

    def access(self, edges):
        origin = next(self.origins[e] for e in edges if e in self.origins)
        destination = next(self.destinations[e] for e in reversed(edges) if e in self.destinations)
        continuous = True
        previous = None
        for e in edges:
            xy = self.edge_coords_xy(int(e))
            if previous is not None and np.linalg.norm(previous - xy[0]) > ON_ROAD_M:
                continuous = False
            previous = xy[-1]
        return {"origin": origin, "destination": destination, "geometry_continuous": continuous,
                "complete": continuous and bool(self.edge_verified[edges].all()) and origin["status"] == destination["status"] == "mapped"}

    def overlap(self, a, b):
        shorter = min(a.path.road_m, b.path.road_m)
        if shorter <= 0:
            return 1. if a.shelter["id"] == b.shelter["id"] else 0.
        def intervals(path):
            out = {}
            for e in path.edges:
                p = int(self.parent[e])
                out.setdefault(p, []).append((self.frac0[e], self.frac1[e]))
            return out
        aa, bb = intervals(a.path), intervals(b.path)
        shared = 0.
        for p in aa.keys() & bb.keys():
            for lo, hi in aa[p]:
                for left, right in bb[p]:
                    shared += max(0., min(hi, right) - max(lo, left)) * self.base.edge_len_m[p]
        return min(1., shared / shorter)

    def fire(self, base_fire, oracle):
        """Clip cached cell intervals, preserving cell-exit timing on partial roads."""
        table = base_fire.table
        starts = table.cell_ptr[self.parent]
        counts = table.cell_ptr[self.parent + 1] - starts
        owners = np.repeat(np.arange(self.n_edges), counts)
        rows = np.repeat(starts, counts) + np.arange(int(counts.sum())) - np.repeat(
            np.cumsum(counts) - counts, counts)
        lo = (self.frac0 * self.base.edge_len_m[self.parent])[owners]
        hi = (self.frac1 * self.base.edge_len_m[self.parent])[owners]
        keep = (table.cell_leave_m[rows] >= lo-1e-7) & (table.cell_enter_m[rows] <= hi+1e-7)
        rows, owners, lo, hi = rows[keep], owners[keep], lo[keep], hi[keep]
        counts = np.bincount(owners, minlength=self.n_edges)
        if not counts.all():
            raise ValueError("A clipped road has no forecast-cell representation")
        clipped = CellTable(table.grid, np.r_[0, np.cumsum(counts)], table.cell_flat[rows],
                            np.maximum(0., table.cell_enter_m[rows] - lo),
                            np.maximum(0., np.minimum(hi, table.cell_leave_m[rows]) - lo))
        arrival, unknown = base_fire.cell_A[rows], base_fire.cell_unknown[rows]
        # A zero-duration road still has spatial geometry. Scaled cached
        # distances are all zero, so they cannot clip a partial traversal.
        zero = np.flatnonzero((self.base.edge_len_m[self.parent] == 0) &
                              ((self.frac0 != 0) | (self.frac1 != 1)))
        if len(zero):
            keep = ~np.isin(owners, zero)
            own, flat, enter, leave = [owners[keep]], [clipped.cell_flat[keep]], [clipped.cell_enter_m[keep]], [clipped.cell_leave_m[keep]]
            for e in zero:
                xy = self.edge_coords_xy(int(e))
                cells = np.concatenate([traverse_segment(a, b, table.grid)[0] for a, b in zip(xy[:-1], xy[1:])])
                own.append(np.full(len(cells), e))
                flat.append(cells)
                enter.append(np.zeros(len(cells)))
                leave.append(np.zeros(len(cells)))
            own, flat, enter, leave = map(np.concatenate, (own, flat, enter, leave))
            order = np.argsort(own, kind="stable")
            clipped = CellTable(table.grid, np.r_[0, np.cumsum(np.bincount(own, minlength=self.n_edges))],
                                flat[order], enter[order], leave[order])
            arrival, unknown = arrival_at_cells(oracle, clipped.cell_flat)
        slack = np.minimum(arrival, oracle.covers_until_sim_min) - BUFFER_MIN - clipped.cell_leave_m / 500.
        slack[unknown] = -np.inf
        deadlines = np.minimum.reduceat(slack, clipped.cell_ptr[:-1])
        deadlines[~self.edge_permitted | ~self.edge_verified] = -np.inf
        return EdgeFire(oracle, self, clipped, arrival, unknown, deadlines)


def designated_road_endpoints(base, origin, shelters, origin_snaps):
    """Nearest projected point among directed, geometrically reachable roads.

    Reachability is geographic, independent of fire: a threatened designated
    endpoint stays blocked instead of silently becoming a different destination.
    """
    from backend.routing.road_graph import shortest_paths
    graph = JourneyGraph(base, origin, [], origin_snaps, {})
    last = base.geom_ptr[graph.parent + 1] - 1
    meets_end = np.hypot(base.geom_x[last]-base.node_x[base.edge_v[graph.parent]],
                         base.geom_y[last]-base.node_y[base.edge_v[graph.parent]]) <= ON_ROAD_M
    allowed = graph.edge_permitted & (graph.edge_verified | ((graph.edge_u == graph.start) & meets_end))
    tree = shortest_paths(graph.n_nodes, graph.edge_u, graph.edge_v,
                          graph.edge_weight, graph.start, allowed)
    p = base.geom_ptr[:-1]
    starts_match = np.hypot(base.geom_x[p]-base.node_x[base.edge_u],
                            base.geom_y[p]-base.node_y[base.edge_u]) <= ON_ROAD_M
    reachable = base.edge_permitted & starts_match & np.isfinite(tree.distance[base.edge_u])
    out = {}
    for shelter in shelters:
        lon, lat = shelter['geometry']['coordinates']
        point = Point(TO_GRID.transform(lon, lat))
        radius = ACCESS_RADIUS_M
        while True:
            ids = base.edge_tree.query(box(point.x-radius, point.y-radius,
                                           point.x+radius, point.y+radius))
            ids = np.sort(ids[base.edge_permitted[ids]])
            fractions = shapely.line_locate_point(base.edge_lines[ids], point, normalized=True)
            fractions = np.nan_to_num(fractions, nan=0.)
            possible = reachable[ids].copy()
            for snap in origin_snaps:
                partial = (ids == snap.edge) & ~reachable[ids]
                fractions[partial] = np.maximum(fractions[partial], snap.fraction)
                possible |= ids == snap.edge
            ids, fractions = ids[possible], fractions[possible]
            points = shapely.line_interpolate_point(base.edge_lines[ids], fractions, normalized=True)
            distances = shapely.distance(points, point)
            if len(ids) and distances.min() <= radius:
                break
            # The bounding rectangle eventually encloses the entire finite map.
            xs, ys = base.geom_x, base.geom_y
            limit = max(abs(point.x-xs.min()), abs(point.x-xs.max()),
                        abs(point.y-ys.min()), abs(point.y-ys.max())) + 1
            if radius >= limit:
                break
            radius = min(radius*2, limit)
        if not len(ids):
            out[shelter['id']] = []
            continue
        pick = int(np.argmin(distances))  # stable original keyed-edge tie break
        projected = points[pick]
        ll = tuple(map(float, TO_LONLAT.transform(projected.x, projected.y)))
        # Every directed road through that one point, so a two-way street can be
        # approached from either side without looping round the block.
        same = np.flatnonzero(shapely.distance(points, projected) <= ON_ROAD_M)
        out[shelter['id']] = [Snap(int(ids[k]), float(fractions[k]), ll, 0., True,
                                   'Designated reachable road endpoint; building access unverified')
                              for k in same]
    return out
