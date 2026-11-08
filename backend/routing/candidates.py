"""Candidate routes for routing v3, found with SciPy's compiled Dijkstra.

Per request, from the pin's nearest road node:

1. One plain search by travel time reaches every shelter. The K_SHELTERS open
   shelters nearest by road each get their usual road (role `fastest`).
2. With a fire running and some usual road not `ok`: the iterated safe search finds
   the fastest route that clears every road deadline (exact; see `safe_search`),
   then one search weighted toward roads with spare time. Each shelter gets the
   roomier road if it judges safe, else the guaranteed one (role `safest`).
3. With fewer than two distinct usable routes: up to two penalty searches for a
   different road to the top shelter (role `alternative`).

The route the phone is following (`keep_id`) is always rebuilt when its shelter is
still among the nearest, even when it now matches another route or no longer clears
the fire, so the answer can show it greyed. Every candidate is judged exactly
(`safety.judge`) before selection.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.sparse.csgraph import dijkstra

from backend.routing.road_graph import SPEED_KM_PER_MIN, TO_GRID, RoadGraph, masked_csr
from backend.routing.safety import OK_MIN, EdgeFire, Judgement, RoutePath, judge

log = logging.getLogger(__name__)

K_SHELTERS = 5
SNAP_MAX_M = 300
MAX_OVERLAP = 0.8
ALT_PENALTY = 1.6
ALT_MAX_STRETCH = 1.4
ALT_TRIES = 2
MAX_FIXPOINT_ROUNDS = 20
ROOMY_WEIGHT = 2.0        # a road with 0 min spare costs 1 + 2 = 3x its travel time

ROLES = ("fastest", "safest", "alternative")


class NoRouteError(Exception):
    """No route can be offered at all (outside the area, no road, no reachable shelter)."""


@dataclass(eq=False)
class Candidate:
    shelter: dict
    role: str
    path: RoutePath
    judgement: Optional[Judgement] = None

    @property
    def id(self) -> str:
        return f"rt_{self.shelter['id']}_{self.role}"

    @property
    def status(self) -> str:
        return self.judgement.status


@dataclass
class SafeSearch:
    arrival: np.ndarray       # (N,) sim minute the driver can reach each node safely, inf if never
    pred: np.ndarray          # (N,) predecessor node, -9999 for none
    allowed: np.ndarray       # (E,) edges left after removing every road entered too late
    rounds: int
    converged: bool


@dataclass
class Stats:
    snap_ms: float = 0.0
    search_ms: float = 0.0
    safety_ms: float = 0.0
    fixpoint_rounds: int = 0
    excluded: list = field(default_factory=list)


def safe_search(n: int, edge_u: np.ndarray, edge_v: np.ndarray, edge_time: np.ndarray,
                deadline: np.ndarray, start: int, t0: float,
                max_rounds: int = MAX_FIXPOINT_ROUNDS) -> SafeSearch:
    """Earliest safe arrival at every node, where edge e may be entered only by deadline[e].

    Repeats: search the allowed roads; drop every allowed road whose start node is
    reached after its deadline. Exact, because at a fixed speed arriving earlier is
    never worse and dropping roads only makes arrivals later, so a dropped road can
    never become usable again. Edges must be sorted by (u, v) with no duplicates.
    """
    allowed = np.ones(len(edge_u), dtype=bool)
    rounds = 0
    while True:
        rounds += 1
        dist, pred = dijkstra(masked_csr(n, edge_u, edge_v, edge_time, allowed), directed=True,
                              indices=start, return_predecessors=True)
        arrival = t0 + dist
        at_u = arrival[edge_u]
        late = allowed & np.isfinite(at_u) & (at_u > deadline + 1e-9)
        if not late.any():
            return SafeSearch(arrival, pred, allowed, rounds, True)
        allowed &= ~late
        if rounds >= max_rounds:
            log.warning("safe search hit %d rounds without settling; using the last roads left", rounds)
            dist, pred = dijkstra(masked_csr(n, edge_u, edge_v, edge_time, allowed), directed=True,
                                  indices=start, return_predecessors=True)
            return SafeSearch(t0 + dist, pred, allowed, rounds, False)


def roomier_search(n: int, edge_u: np.ndarray, edge_v: np.ndarray, edge_time: np.ndarray,
                   deadline: np.ndarray, safe: SafeSearch, start: int):
    """One search over the safe roads, each costing more the less spare time it has:
    time * (1 + 2 * shortfall), shortfall = max(0, 60 - spare) / 60. Returns (cost, pred).

    Ordered by cost, not time, so its roads must still be judged; a road it picks
    may be unsafe when reached later than in the guaranteed search.
    """
    at_u = safe.arrival[edge_u]
    usable = safe.allowed & np.isfinite(at_u)
    with np.errstate(invalid="ignore"):
        spare = np.where(usable, deadline - np.where(usable, at_u, 0.0), np.inf)
    shortfall = np.clip((OK_MIN - spare) / OK_MIN, 0.0, None)
    cost = edge_time * (1.0 + ROOMY_WEIGHT * shortfall)
    return dijkstra(masked_csr(n, edge_u, edge_v, cost, usable), directed=True,
                    indices=start, return_predecessors=True)


def path_nodes(pred: np.ndarray, start: int, target: int) -> Optional[list]:
    """Node path from start to target out of a predecessor array, or None."""
    if target == start:
        return [start]
    if pred[target] < 0:
        return None
    nodes = [target]
    while nodes[-1] != start:
        prev = int(pred[nodes[-1]])
        if prev < 0 or len(nodes) > len(pred):
            return None
        nodes.append(prev)
    nodes.reverse()
    return nodes


def overlap(rg: RoadGraph, a: Candidate, b: Candidate) -> float:
    """Shared road length / the shorter route's road length."""
    ea, eb = a.path.edges, b.path.edges
    if not len(ea) or not len(eb):
        same = a.shelter["id"] == b.shelter["id"] and not len(ea) and not len(eb)
        return 1.0 if same else 0.0
    shorter = min(a.path.road_m, b.path.road_m)
    if shorter <= 0:
        return 1.0
    shared = np.intersect1d(ea, eb, assume_unique=True)
    return float(rg.edge_len_m[shared].sum()) / shorter


def eligible(shelters: list, excluded: list) -> list:
    """Open shelters with room. Closed and full ones go to `excluded`."""
    out = []
    for s in shelters:
        props = s["properties"]
        if not props.get("open", False):
            excluded.append({"shelter_id": s["id"], "reason": "Shelter closed"})
        elif props.get("occupancy", 0) >= props.get("capacity", 0):
            excluded.append({"shelter_id": s["id"], "reason": "Shelter full"})
        else:
            out.append(s)
    return out


def build_candidates(rg: RoadGraph, edge_fire: Optional[EdgeFire], oracle, lat: float, lon: float,
                     shelters: list, t_now: float, stats: Stats, keep_id: Optional[str] = None) -> list:
    """All candidate routes from the pin, each judged. Raises NoRouteError for the 404 cases."""
    kept_sid, kept_role = parse_id(keep_id)
    clock = time.perf_counter()
    start, snap_m = rg.nearest_node(lat, lon)
    stats.snap_ms += (time.perf_counter() - clock) * 1000
    if snap_m > SNAP_MAX_M:
        raise NoRouteError("No road near this location")
    pin_ll = (float(lon), float(lat))
    pin_xy = tuple(float(c) for c in TO_GRID.transform(lon, lat))
    join_ll = (float(rg.node_lon[start]), float(rg.node_lat[start]))
    join_xy = (float(rg.node_x[start]), float(rg.node_y[start]))
    connector_min = snap_m / 1000.0 / SPEED_KM_PER_MIN

    def make_path(shelter, nodes) -> RoutePath:
        edges = rg.path_edges(nodes)
        s_lon, s_lat = (float(c) for c in shelter["geometry"]["coordinates"])
        return RoutePath(pin_ll, pin_xy, join_ll, join_xy, edges, float(rg.edge_len_m[edges].sum()),
                         (s_lon, s_lat), tuple(float(c) for c in TO_GRID.transform(s_lon, s_lat)),
                         shelter["properties"].get("name", shelter["id"]))

    def judged(c: Candidate) -> Candidate:
        tick = time.perf_counter()
        c.judgement = judge(c.path, t_now, oracle, edge_fire)
        stats.safety_ms += (time.perf_counter() - tick) * 1000
        return c

    # 1. Plain search: shelters by driving distance, and their usual roads.
    tick = time.perf_counter()
    dist, pred = dijkstra(rg.csr_time, directed=True, indices=start, return_predecessors=True)
    stats.search_ms += (time.perf_counter() - tick) * 1000
    reachable = []
    for s in eligible(shelters, stats.excluded):
        s_lon, s_lat = s["geometry"]["coordinates"]
        node, _ = rg.nearest_node(float(s_lat), float(s_lon))
        if np.isfinite(dist[node]):
            reachable.append((float(dist[node]), s["id"], s, node))
        else:
            stats.excluded.append({"shelter_id": s["id"], "reason": "Not reachable by road"})
    if not reachable:
        raise NoRouteError("No open shelter can be reached by road")
    reachable.sort(key=lambda r: (r[0], r[1]))
    kept = [(s, node) for _, _, s, node in reachable[:K_SHELTERS]]

    fastest = {}
    for s, node in kept:
        fastest[s["id"]] = judged(Candidate(s, "fastest", make_path(s, path_nodes(pred, start, node))))
    candidates = list(fastest.values())

    # 2. Safest: the iterated safe search, then a roomier pass over the safe roads.
    safe = None
    w = rg.edge_weight
    if edge_fire is not None and (any(c.status != "ok" for c in candidates) or kept_role == "safest"):
        tick = time.perf_counter()
        safe = safe_search(rg.n_nodes, rg.edge_u, rg.edge_v, w, edge_fire.edge_deadline,
                           start, t_now + connector_min)
        _, roomy_pred = roomier_search(rg.n_nodes, rg.edge_u, rg.edge_v, w, edge_fire.edge_deadline,
                                       safe, start)
        stats.search_ms += (time.perf_counter() - tick) * 1000
        stats.fixpoint_rounds = safe.rounds
        for s, node in kept:
            is_kept = (s["id"], "safest") == (kept_sid, kept_role)
            if np.isfinite(safe.arrival[node]):
                pick = None
                roomy = path_nodes(roomy_pred, start, node)
                if roomy is not None:
                    pick = judged(Candidate(s, "safest", make_path(s, roomy)))
                if pick is None or pick.status == "blocked":
                    pick = judged(Candidate(s, "safest", make_path(s, path_nodes(safe.pred, start, node))))
            elif is_kept:
                # The phone's safest road no longer clears the fire: show its roomiest
                # version over all roads, which judges blocked.
                tick = time.perf_counter()
                everywhere = SafeSearch(t_now + connector_min + dist, pred, np.ones(rg.n_edges, bool), 0, True)
                _, worst_pred = roomier_search(rg.n_nodes, rg.edge_u, rg.edge_v, w,
                                               edge_fire.edge_deadline, everywhere, start)
                stats.search_ms += (time.perf_counter() - tick) * 1000
                pick = judged(Candidate(s, "safest", make_path(s, path_nodes(worst_pred, start, node))))
            else:
                continue
            if is_kept or overlap(rg, pick, fastest[s["id"]]) <= MAX_OVERLAP:
                candidates.append(pick)

    # 3. Alternatives when there are fewer than two distinct usable routes, and the phone's own.
    from backend.routing.select import rank_key  # selection owns the ranking

    nodes_of = {s["id"]: node for s, node in kept}
    bases = [min(candidates, key=rank_key)] if _distinct_usable(rg, candidates) < 2 else []
    if kept_role == "alternative" and kept_sid in fastest and all(b.shelter["id"] != kept_sid for b in bases):
        bases.append(fastest[kept_sid])
    for base in bases:
        candidates.extend(_alternative(rg, base, nodes_of[base.shelter["id"]], start, safe,
                                       make_path, judged, stats))
    return candidates


def parse_id(route_id: Optional[str]) -> tuple:
    """rt_<shelter_id>_<role> -> (shelter_id, role); (None, None) if it isn't one."""
    if not route_id or not route_id.startswith("rt_"):
        return None, None
    sid, _, role = route_id[3:].rpartition("_")
    return (sid, role) if sid and role in ROLES else (None, None)


def _distinct_usable(rg, candidates) -> int:
    kept = []
    for c in candidates:
        if c.status != "blocked" and all(overlap(rg, c, k) <= MAX_OVERLAP for k in kept):
            kept.append(c)
    return len(kept)


def _alternative(rg, best, node, start, safe, make_path, judged, stats) -> list:
    """A different road to best's shelter: penalise best's roads and search again."""
    if best.path.road_m <= 0:
        return []
    weights = rg.edge_weight.copy()
    allowed = safe.allowed if safe is not None else None
    penalised = best.path.edges
    for _ in range(ALT_TRIES):
        weights[penalised] *= ALT_PENALTY
        tick = time.perf_counter()
        _, pred = dijkstra(rg.masked_csr(weights, allowed), directed=True, indices=start,
                           return_predecessors=True)
        stats.search_ms += (time.perf_counter() - tick) * 1000
        nodes = path_nodes(pred, start, node)
        if nodes is None:
            return []
        alt = Candidate(best.shelter, "alternative", make_path(best.shelter, nodes))
        if overlap(rg, alt, best) <= MAX_OVERLAP and alt.path.road_m <= ALT_MAX_STRETCH * best.path.road_m:
            return [judged(alt)]
        penalised = alt.path.edges
    return []


def straight_line_candidates(lat, lon, shelters, oracle, t_now, k, inside, stats) -> list:
    """No road graph: straight lines to the nearest open shelters, still judged cell by cell."""
    pin_ll = (float(lon), float(lat))
    pin_xy = tuple(float(c) for c in TO_GRID.transform(lon, lat))
    found = []
    for s in eligible(shelters, stats.excluded):
        s_lon, s_lat = (float(c) for c in s["geometry"]["coordinates"])
        if not inside(s_lat, s_lon):
            stats.excluded.append({"shelter_id": s["id"], "reason": "Outside the demo area"})
            continue
        s_xy = tuple(float(c) for c in TO_GRID.transform(s_lon, s_lat))
        found.append((math.hypot(s_xy[0] - pin_xy[0], s_xy[1] - pin_xy[1]), s["id"], s, s_xy))
    if not found:
        raise NoRouteError("No open shelter can be reached by road")
    found.sort(key=lambda f: (f[0], f[1]))
    out = []
    for _, _, s, s_xy in found[:k]:
        path = RoutePath(pin_ll, pin_xy, (s["geometry"]["coordinates"][0], s["geometry"]["coordinates"][1]),
                         s_xy, np.zeros(0, dtype=np.int64), 0.0, tuple(s["geometry"]["coordinates"]), s_xy,
                         s["properties"].get("name", s["id"]), approximate=True)
        tick = time.perf_counter()
        out.append(Candidate(s, "fastest", path, judge(path, t_now, oracle, None)))
        stats.safety_ms += (time.perf_counter() - tick) * 1000
    return out
