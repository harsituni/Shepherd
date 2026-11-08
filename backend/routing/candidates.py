"""Candidate routes for routing v3, found with SciPy's compiled Dijkstra.

Per request, from directed edge projections at the pin:

1. One plain search by travel time reaches every eligible shelter. Each reachable
   shelter gets its usual road (role `fastest`); there is no destination cutoff.
2. With a fire running and some usual road not `ok`: the iterated safe search finds
   the fastest route that clears every road deadline (exact; see `safe_search`),
   then one search weighted toward roads with spare time. Each shelter gets the
   roomier road if it judges safe, else the guaranteed one (role `safest`).
3. With fewer than two distinct usable routes: up to two penalty searches for a
   different road to the top shelter (role `alternative`).

The route the phone is following (`keep_id`) is always rebuilt when its shelter is
still reachable, even when it now matches another route or no longer clears
the fire, so the answer can show it greyed. Every candidate is judged exactly
(`safety.judge`) before selection.
"""

from __future__ import annotations

import logging
import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from backend.routing.road_graph import SPEED_KM_PER_MIN, TO_GRID, RoadGraph, shortest_paths, edge_path
from backend.routing.access import ON_ROAD_M, JourneyGraph, road_start, snaps, designated_road_endpoints
from backend.routing.safety import BUFFER_MIN, EPS_MIN, OK_MIN, EdgeFire, Judgement, RoutePath, judge, viable

log = logging.getLogger(__name__)

MAX_OVERLAP = 0.8
ALT_PENALTY = 1.6
ALT_MAX_STRETCH = 1.4
ALT_TRIES = 2
COMPILED_SEARCH_ROUNDS = 20  # performance switch to exact heap search, never a correctness cap
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
    pred_edge: Optional[np.ndarray] = None
    used_fallback: bool = False

    def edges_to(self, start, target):
        return edge_path(self.pred, self.pred_edge, start, target)


@dataclass
class Stats:
    snap_ms: float = 0.0
    search_ms: float = 0.0
    safety_ms: float = 0.0
    fixpoint_rounds: int = 0
    exact_fallbacks: int = 0
    search_complete: bool = False
    search_scope: str = "all_eligible_shelters_on_loaded_directed_graph"
    shelters_evaluated: int = 0
    excluded: list = field(default_factory=list)
    routing_graph: object = None


def safe_search(n: int, edge_u: np.ndarray, edge_v: np.ndarray, edge_time: np.ndarray,
                deadline: np.ndarray, start: int, t0: float,
                max_rounds: int = COMPILED_SEARCH_ROUNDS) -> SafeSearch:
    """Earliest safe arrival at every node, where edge e may be entered only by deadline[e].

    Repeats: search the allowed roads; drop every allowed road whose start node is
    reached after its deadline. Exact, because at a fixed speed arriving earlier is
    never worse and dropping roads only makes arrivals later, so a dropped road can
    never become usable again. Parallel roads have individual deadlines and are
    reduced by minimum cost only within each search. Edges are sorted by (u, v).
    max_rounds only selects the compiled/heap execution strategy; both are exact.
    """
    allowed = np.ones(len(edge_u), dtype=bool)
    rounds = 0
    while True:
        rounds += 1
        tree = shortest_paths(n, edge_u, edge_v, edge_time, start, allowed)
        dist, pred = tree
        arrival = t0 + dist
        at_u = arrival[edge_u]
        late = allowed & np.isfinite(at_u) & (at_u > deadline + EPS_MIN)
        if not late.any():
            return SafeSearch(arrival, pred, allowed, rounds, True, tree.pred_edge)
        allowed &= ~late
        if rounds >= max_rounds:
            return _constrained_heap(n, edge_u, edge_v, edge_time, deadline, start, t0, rounds)


def _constrained_heap(n, u, v, weights, deadline, start, t0, rounds):
    """Exact earliest-arrival labels: earlier arrival dominates all later labels.

    Each outgoing edge is relaxed only if its own deadline permits entry. With
    nonnegative travel times and deadlines that only close, waiting/cycles cannot
    help. This is label-setting Dijkstra with an edge-entry feasibility predicate.
    """
    ptr = np.r_[0, np.cumsum(np.bincount(u, minlength=n))]
    arrival = np.full(n, np.inf)
    pred, pred_edge = np.full(n, -9999, dtype=int), np.full(n, -1, dtype=int)
    arrival[start] = t0
    heap = [(t0, start)]
    while heap:
        at, node = heapq.heappop(heap)
        if at != arrival[node]:
            continue
        for e in range(ptr[node], ptr[node + 1]):
            if at > deadline[e] + EPS_MIN:
                continue
            target, end = int(v[e]), at + weights[e]
            if end < arrival[target]:
                arrival[target], pred[target], pred_edge[target] = end, node, e
                heapq.heappush(heap, (end, target))
    allowed = np.isfinite(arrival[u]) & (arrival[u] <= deadline + EPS_MIN)
    return SafeSearch(arrival, pred, allowed, rounds, True, pred_edge, True)


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
    # A zero-duration edge remains zero cost, including when an unknown/blocked
    # deadline gives infinite shortfall in the selected-route display fallback.
    cost = np.zeros_like(edge_time)
    np.multiply(edge_time, 1.0 + ROOMY_WEIGHT * shortfall, out=cost, where=edge_time > 0)
    return shortest_paths(n, edge_u, edge_v, cost, start, usable)


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
    if hasattr(rg, "overlap"):
        return rg.overlap(a, b)
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
    starts = road_start(rg, lon, lat)
    if not starts:
        raise NoRouteError("No accessible mapped road within 300 m of this location")
    shelters = eligible(shelters, stats.excluded)
    designated = [s for s in shelters if s["properties"].get("routing_endpoint") == "reachable_road_point"]
    ends = {s["id"]: snaps(rg, *s["geometry"]["coordinates"], destination=True)
            for s in shelters if s not in designated}
    # The nearest start that reaches any shelter (a one-way road may lead away).
    base, searched = rg, 0.
    from backend.routing.traffic import engine as traffic_engine
    for origin in starts:
        road_ends = designated_road_endpoints(base, (lon, lat), designated, origin) if designated else {}
        rg = JourneyGraph(base, (lon, lat), shelters, origin, {**ends, **road_ends})
        # When traffic is on, BPR scales free-flow weights from current edge volumes.
        traffic_engine.apply_journey_weights(rg)
        tick = time.perf_counter()
        plain = shortest_paths(rg.n_nodes, rg.edge_u, rg.edge_v, rg.edge_weight, rg.start, rg.edge_permitted)
        searched += time.perf_counter() - tick
        if any(np.isfinite(plain.distance[node]) for node in rg.targets.values()):
            break
    stats.routing_graph = rg
    if edge_fire is not None:
        edge_fire = rg.fire(edge_fire, oracle)
    stats.snap_ms += (time.perf_counter() - clock - searched) * 1000
    stats.search_ms += searched * 1000
    start = rg.start
    pin_ll = (float(lon), float(lat))
    pin_xy = tuple(float(c) for c in TO_GRID.transform(lon, lat))
    # Unmapped gaps are metadata, never invented traversable straight lines. The
    # person's own cell is still judged at departure (zero distance, no time).
    join_ll, join_xy, connector_min = pin_ll, pin_xy, 0.
    from_road_point = origin[0].verified and origin[0].gap_m > ON_ROAD_M

    def make_path(shelter, edges) -> RoutePath:
        s_lon, s_lat = (float(c) for c in shelter["geometry"]["coordinates"])
        access = rg.access(edges)
        if from_road_point:
            start = access["origin"]
            access["origin"] = {**start, "kind": "designated_road_point", "point": start["road_point"],
                                "gap_m": 0., "person_point": list(pin_ll), "person_access_verified": False,
                                "unmodeled_m": start["gap_m"]}
        if shelter["id"] in road_ends:
            s_lon, s_lat = access["destination"]["road_point"]
            b_x, b_y = TO_GRID.transform(*shelter["geometry"]["coordinates"])
            r_x, r_y = TO_GRID.transform(s_lon, s_lat)
            access["destination"].update({"kind": "designated_road_point",
                "building_point": list(shelter["geometry"]["coordinates"]),
                "building_access_verified": False, "point": [s_lon, s_lat],
                "unmodeled_m": float(math.hypot(b_x - r_x, b_y - r_y))})
        duration = float(rg.edge_weight[edges].sum()) if len(edges) else 0.0
        return RoutePath(pin_ll, pin_xy, join_ll, join_xy, edges, float(rg.edge_len_m[edges].sum()),
                         (s_lon, s_lat), tuple(float(c) for c in TO_GRID.transform(s_lon, s_lat)),
                         shelter["properties"].get("name", shelter["id"]),
                         access=access, access_verified=access["complete"],
                         duration_min=duration)

    def judged(c: Candidate) -> Candidate:
        tick = time.perf_counter()
        c.judgement = judge(c.path, t_now, oracle, edge_fire)
        stats.safety_ms += (time.perf_counter() - tick) * 1000
        return c

    # 1. Plain search (above): shelters by driving distance, and their usual roads.
    dist, pred = plain
    reachable = []
    for s in shelters:
        node = rg.targets[s["id"]]
        if np.isfinite(dist[node]):
            reachable.append((float(dist[node]), s["id"], s, node))
        else:
            stats.excluded.append({"shelter_id": s["id"], "reason": "Not reachable by road"})
    if not reachable:
        raise NoRouteError("No open shelter can be reached by road")
    reachable.sort(key=lambda r: (r[0], r[1]))
    # One all-node search already reaches every destination. Do not discard
    # farther shelters before evaluating their feasibility.
    kept = [(s, node) for _, _, s, node in reachable]
    stats.shelters_evaluated = len(kept)
    stats.search_complete = oracle is None or edge_fire is not None

    fastest = {}
    for s, node in kept:
        fastest[s["id"]] = judged(Candidate(s, "fastest", make_path(s, plain.edges_to(start, node))))
    candidates = list(fastest.values())

    # 2. Safest: the iterated safe search, then a roomier pass over the safe roads.
    safe = None
    w = rg.edge_weight
    deadlines = (edge_fire.edge_deadline.copy() if edge_fire is not None
                 else np.full(rg.n_edges, np.inf))
    deadlines[~rg.edge_permitted | ~rg.edge_verified] = -np.inf
    if any(c.status != "ok" for c in candidates) or kept_role == "safest":
        tick = time.perf_counter()
        safe = safe_search(rg.n_nodes, rg.edge_u, rg.edge_v, w, deadlines,
                           start, t_now + connector_min)
        roomy_tree = roomier_search(rg.n_nodes, rg.edge_u, rg.edge_v, w, deadlines,
                                    safe, start)
        stats.search_ms += (time.perf_counter() - tick) * 1000
        stats.fixpoint_rounds = safe.rounds
        stats.exact_fallbacks += int(safe.used_fallback)
        stats.search_complete &= safe.converged
        for s, node in kept:
            is_kept = (s["id"], "safest") == (kept_sid, kept_role)
            if np.isfinite(safe.arrival[node]):
                pick = None
                roomy = roomy_tree.edges_to(start, node)
                if roomy is not None:
                    pick = judged(Candidate(s, "safest", make_path(s, roomy)))
                if pick is None or not viable(pick.judgement):
                    pick = judged(Candidate(s, "safest", make_path(s, safe.edges_to(start, node))))
            elif is_kept:
                # The phone's safest road no longer clears the fire: show its roomiest
                # version over all roads, which judges blocked.
                tick = time.perf_counter()
                everywhere = SafeSearch(t_now + connector_min + dist, pred,
                                         rg.edge_permitted, 0, True, plain.pred_edge)
                worst = roomier_search(rg.n_nodes, rg.edge_u, rg.edge_v, w,
                                       deadlines, everywhere, start)
                stats.search_ms += (time.perf_counter() - tick) * 1000
                edges = worst.edges_to(start, node)
                if edges is None:
                    edges = plain.edges_to(start, node)
                pick = judged(Candidate(s, "safest", make_path(s, edges)))
            else:
                continue
            if (is_kept or (viable(pick.judgement) and not viable(fastest[s["id"]].judgement))
                    or overlap(rg, pick, fastest[s["id"]]) <= MAX_OVERLAP):
                candidates.append(pick)

    # Before asserting global blockage, search with unknown evidence relaxed.
    # A blocked shortest route does not rule out an indeterminate detour. Only
    # known arrival constraints apply here; judge still enforces Phase 1 in full.
    if not any(viable(c.judgement) for c in candidates):
        tick = time.perf_counter()
        known_deadline = np.full(rg.n_edges, np.inf)
        if edge_fire is not None:
            table = edge_fire.table
            slack = edge_fire.cell_A - BUFFER_MIN - table.cell_leave_m / 1000 / SPEED_KM_PER_MIN
            known_deadline = np.minimum.reduceat(slack, table.cell_ptr[:-1])
        known_deadline[~rg.edge_permitted] = -np.inf
        possible = safe_search(rg.n_nodes, rg.edge_u, rg.edge_v, w, known_deadline,
                               start, t_now + connector_min)
        stats.search_ms += (time.perf_counter() - tick) * 1000
        stats.fixpoint_rounds = max(stats.fixpoint_rounds, possible.rounds)
        stats.exact_fallbacks += int(possible.used_fallback)
        stats.search_complete &= possible.converged
        for s, node in kept:
            edges = possible.edges_to(start, node)
            if edges is None:
                continue
            pick = judged(Candidate(s, "safest", make_path(s, edges)))
            if pick.status != "blocked":
                # Keep a witness to uncertainty even when it overlaps a blocked
                # route. Never change the witness's own safety classification.
                candidates = [c for c in candidates if c.id != pick.id]
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
        if viable(c.judgement) and all(overlap(rg, c, k) <= MAX_OVERLAP for k in kept):
            kept.append(c)
    return len(kept)


def _alternative(rg, best, node, start, safe, make_path, judged, stats) -> list:
    """A different road to best's shelter: penalise best's roads and search again."""
    if best.path.road_m <= 0:
        return []
    weights = rg.edge_weight.copy()
    allowed = safe.allowed if safe is not None else rg.edge_permitted
    penalised = best.path.edges
    for _ in range(ALT_TRIES):
        weights[penalised] *= ALT_PENALTY
        tick = time.perf_counter()
        tree = shortest_paths(rg.n_nodes, rg.edge_u, rg.edge_v, weights, start, allowed)
        stats.search_ms += (time.perf_counter() - tick) * 1000
        edges = tree.edges_to(start, node)
        if edges is None:
            return []
        alt = judged(Candidate(best.shelter, "alternative", make_path(best.shelter, edges)))
        if ((viable(alt.judgement) and not viable(best.judgement))
                or (overlap(rg, alt, best) <= MAX_OVERLAP
                    and alt.path.road_m <= ALT_MAX_STRETCH * best.path.road_m)):
            return [alt]
        penalised = alt.path.edges
    return []


def straight_line_candidates(lat, lon, shelters, oracle, t_now, inside, stats) -> list:
    """No graph: endpoints are diagnostic only; never invent a traversable line."""
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
    stats.search_scope = "road_graph_unavailable"
    stats.shelters_evaluated = len(found)
    stats.search_complete = False
    for _, _, s, s_xy in found:
        path = RoutePath(pin_ll, pin_xy, pin_ll,
                         pin_xy, np.zeros(0, dtype=np.int64), 0.0, tuple(s["geometry"]["coordinates"]), s_xy,
                         s["properties"].get("name", s["id"]), approximate=True)
        tick = time.perf_counter()
        out.append(Candidate(s, "fastest", path, judge(path, t_now, oracle, None)))
        stats.safety_ms += (time.perf_counter() - tick) * 1000
    return out
