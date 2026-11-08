"""Evacuation traffic: BPR travel times, simulated crowd, anti-gridlock assignment.

Not in contract v2 — additive API under /traffic*. When disabled, routing is
unchanged (free-flow 30 km/h). When enabled, edge travel times follow the
Bureau of Public Roads formula and a crowd of cars (plus real phone pins) is
loaded onto the network so jams can blow fire margins and anti-gridlock can
spread demand across shelters/routes.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from backend.routing.road_graph import SPEED_KM_PER_MIN, RoadGraph, shortest_paths

log = logging.getLogger(__name__)

# Full /route for every simulated car freezes the API. Crowd cars use a fast
# Dijkstra on the road graph; only this many get a unique path, the rest clone.
# Higher with multi-thousand crowds so anti-gridlock still paints distinct corridors.
MAX_UNIQUE_ROUTES = 96

# BPR (Bureau of Public Roads) — standard volume-delay.
BPR_ALPHA = 0.15
BPR_BETA = 4.0
# Cap v/c inside BPR so a naive 2k-car pile-up can't produce hundred-million
# minute ETAs (and a broken "Clearance time 297244928 → 15 min" label).
BPR_VC_CAP = 3.0
# Demo metrics / compare labels stay human-readable.
CLEARANCE_CAP_MIN = 480.0  # 8 hours
MAX_VC_REPORT = 5.0

# Static loading capacity (vehicles that can share an edge before it jams).
# Tuned for demo N≈hundreds–thousands, not real hourly freeway flow.
# Per-lane static loading capacity (cars sharing an edge before it jams). Kept
# intentionally low so evacuating crowds create visible gridlock on the map.
CAP_PER_LANE = {
    "motorway": 40,
    "motorway_link": 24,
    "trunk": 32,
    "trunk_link": 20,
    "primary": 22,
    "primary_link": 14,
    "secondary": 16,
    "secondary_link": 12,
    "tertiary": 12,
    "tertiary_link": 9,
    "residential": 7,
    "living_street": 5,
    "unclassified": 9,
    "service": 5,
    "road": 8,
}
DEFAULT_CAP_PER_LANE = 8
DEFAULT_LANES = {
    "motorway": 3,
    "motorway_link": 1,
    "trunk": 2,
    "trunk_link": 1,
    "primary": 2,
    "primary_link": 1,
    "secondary": 2,
    "secondary_link": 1,
    "tertiary": 1,
    "residential": 1,
    "living_street": 1,
    "unclassified": 1,
    "service": 1,
    "road": 1,
}

REBALANCE_EVERY_MIN = 2
# Demo-facing: switch / hint as soon as another path is meaningfully faster so
# judges see Shepherd actively rerouting people out of jams.
SWITCH_SAVE_MIN = 1.0
SWITCH_COOLDOWN_MIN = 2
DEFAULT_SIMULATED = 10_000
# Dashboard can ask for up to 100k evacuating cars. We only instantiate a few
# thousand agents and scale each one's road load (projection) so the API stays fast.
MAX_SIMULATED = 100_000
MAX_SIM_AGENTS = 2_500
# Seed congested edges, then grow hard along the graph so corridors don't break
# at quiet intersection connectors.
MAP_SEED_LIMIT = 900
MAP_EDGE_LIMIT = 2800
MAP_MIN_VC = 0.4
# Any cars at all is enough to keep a connector when it touches a corridor.
MAP_FILL_MIN_VOLUME = 0.05


def _highway_key(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value or "road").lower()


def _parse_lanes(value, highway: str) -> int:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is not None:
        try:
            n = int(float(str(value).split(";")[0].strip()))
            if n >= 1:
                return min(n, 6)
        except (TypeError, ValueError):
            pass
    return DEFAULT_LANES.get(highway, 1)


def bpr_factor(volume: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """t / t0 = 1 + α (v/c)^β. Capacity floored so empty edges stay free-flow.

    v/c is capped so extreme demo crowds still jam roads without overflowing
    float travel times used in clearance / compare copy.
    """
    c = np.maximum(capacity.astype(np.float64), 1.0)
    vc = np.maximum(volume.astype(np.float64), 0.0) / c
    vc = np.minimum(vc, BPR_VC_CAP)
    return 1.0 + BPR_ALPHA * np.power(vc, BPR_BETA)


def _sane_minutes(value: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return CLEARANCE_CAP_MIN
    return float(min(CLEARANCE_CAP_MIN, max(0.0, float(value))))


@dataclass
class Agent:
    id: str
    lat: float
    lon: float
    kind: str  # "sim" | "phone"
    shelter_id: Optional[str] = None
    route_id: Optional[str] = None
    edge_ids: tuple = ()          # base RoadGraph edge indices
    eta_min: float = 0.0
    free_eta_min: float = 0.0
    assigned_sim_min: int = 0
    last_switch_sim_min: int = -10_000
    arrived: bool = False
    # How many projected cars this agent represents on the network (phones = 1).
    load_weight: float = 1.0


@dataclass
class TrafficMetrics:
    clearance_min: Optional[float] = None
    avg_eta_min: Optional[float] = None
    max_vc: float = 0.0
    jammed_edges: int = 0
    agents_active: int = 0
    agents_arrived: int = 0
    reroutes: int = 0

    def as_dict(self) -> dict:
        return {
            "clearance_min": None if self.clearance_min is None else round(self.clearance_min, 1),
            "avg_eta_min": None if self.avg_eta_min is None else round(self.avg_eta_min, 1),
            "max_vc": round(self.max_vc, 2),
            "jammed_edges": int(self.jammed_edges),
            "agents_active": int(self.agents_active),
            "agents_arrived": int(self.agents_arrived),
            "reroutes": int(self.reroutes),
        }


class TrafficEngine:
    """In-memory traffic state for the loaded road graph."""

    def __init__(self) -> None:
        self.enabled = False
        self.anti_gridlock = True
        self.simulated_count = DEFAULT_SIMULATED
        self._lock = threading.RLock()
        self._rg: Optional[RoadGraph] = None
        self._capacity = np.zeros(0)
        self._highway: tuple = ()
        self._lanes = np.zeros(0, dtype=np.int16)
        self._volume = np.zeros(0)
        self._agents: dict[str, Agent] = {}
        self._last_rebalance_sim = -10_000
        self._metrics = TrafficMetrics()
        self._compare: Optional[dict] = None
        self._rng = np.random.default_rng(42)
        self._route_fn = None  # optional; phones may still use full /route
        self._shelters_fn = None
        # Spawn cluster centre (hazard origin). Defaults to central Edmonton.
        self.cluster_lat = 53.5461
        self.cluster_lon = -113.4938
        self._assign_thread: Optional[threading.Thread] = None
        self._assign_pending: Optional[tuple] = None  # (force, sim_time)

    # ----- graph binding -----

    def bind_graph(self, nx_graph, rg: RoadGraph) -> None:
        """Build per-edge capacity aligned with RoadGraph edge order."""
        with self._lock:
            self._rg = rg
            caps = []
            highways = []
            lanes_arr = []
            # Rebuild the same edge order RoadGraph.from_networkx uses.
            source = (nx_graph.edges(keys=True, data=True) if nx_graph.is_multigraph()
                      else ((u, v, 0, data) for u, v, data in nx_graph.edges(data=True)))
            index = {osmid: i for i, osmid in enumerate(rg.node_osmid)}
            roads = [(index[u], index[v], key, data) for u, v, key, data in source]
            roads.sort(key=lambda e: (e[0], e[1], float(e[3].get("length", 0.0)),
                                      type(e[2]).__name__, repr(e[2])))
            if len(roads) != rg.n_edges:
                raise ValueError(f"traffic edge count {len(roads)} != road graph {rg.n_edges}")
            for _, _, _, data in roads:
                hwy = _highway_key(data.get("highway"))
                lanes = _parse_lanes(data.get("lanes"), hwy)
                cap = lanes * CAP_PER_LANE.get(hwy, DEFAULT_CAP_PER_LANE)
                # Slight length bonus so long arterials absorb more cars.
                length_km = max(0.05, float(data.get("length", 50.0)) / 1000.0)
                cap = max(4.0, cap * (0.7 + 0.3 * min(length_km, 2.0)))
                caps.append(cap)
                highways.append(hwy)
                lanes_arr.append(lanes)
            self._capacity = np.asarray(caps, dtype=np.float64)
            self._highway = tuple(highways)
            self._lanes = np.asarray(lanes_arr, dtype=np.int16)
            self._volume = np.zeros(rg.n_edges, dtype=np.float64)
            self._agents.clear()
            self._metrics = TrafficMetrics()
            self._compare = None
            self._last_rebalance_sim = -10_000

    def set_callbacks(self, route_fn, shelters_fn) -> None:
        self._route_fn = route_fn
        self._shelters_fn = shelters_fn

    def set_cluster(self, lat: float, lon: float) -> None:
        """Concentrate the simulated crowd near the active hazard."""
        with self._lock:
            self.cluster_lat = float(lat)
            self.cluster_lon = float(lon)
            # Drop simulated cars so the next ensure respawns them near the hotspot.
            for eid in list(self._agents):
                if self._agents[eid].kind == "sim":
                    self._unload_agent_locked(self._agents.pop(eid))

    # ----- config -----

    def configure(self, *, enabled: Optional[bool] = None,
                  anti_gridlock: Optional[bool] = None,
                  simulated_count: Optional[int] = None) -> dict:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if anti_gridlock is not None:
                self.anti_gridlock = bool(anti_gridlock)
            if simulated_count is not None:
                self.simulated_count = max(0, min(MAX_SIMULATED, int(simulated_count)))
            if self.enabled and self._rg is not None:
                self._ensure_crowd_locked()
                # Never block the HTTP thread on hundreds of routes.
                self._schedule_assign_locked(force=True, sim_time=0)
            elif not self.enabled:
                self._assign_pending = None
                for eid in list(self._agents):
                    if self._agents[eid].kind == "sim":
                        self._unload_agent_locked(self._agents.pop(eid))
                if len(self._volume):
                    self._volume[:] = 0
                self._metrics = TrafficMetrics()
                self._compare = None
                self._last_rebalance_sim = -10_000
            return self.status_locked()

    def _schedule_assign_locked(self, force: bool = False, sim_time: int = 0) -> None:
        """Queue a background reassignment (caller holds the lock)."""
        self._assign_pending = (bool(force), int(sim_time))
        t = self._assign_thread
        if t is not None and t.is_alive():
            return

        def worker() -> None:
            while True:
                with self._lock:
                    pending = self._assign_pending
                    self._assign_pending = None
                if pending is None:
                    return
                force_f, sim_t = pending
                try:
                    with self._lock:
                        if not self.enabled or self._rg is None:
                            continue
                        self._ensure_crowd_locked()
                        self._assign_all_locked(force=force_f, sim_time=sim_t)
                        self._last_rebalance_sim = int(sim_t)
                except Exception:  # noqa: BLE001
                    log.exception("traffic assignment failed")

        self._assign_thread = threading.Thread(target=worker, daemon=True, name="traffic-assign")
        self._assign_thread.start()

    def _projection_weight_locked(self) -> float:
        """Cars-per-sim-agent so N agents can stand in for up to 100k evacuating cars."""
        n = sum(1 for a in self._agents.values() if a.kind == "sim")
        if n <= 0:
            return 1.0
        return max(1.0, float(self.simulated_count) / float(n))

    def status_locked(self) -> dict:
        phones = sum(1 for a in self._agents.values() if a.kind == "phone" and not a.arrived)
        sims = sum(1 for a in self._agents.values() if a.kind == "sim" and not a.arrived)
        weight = self._projection_weight_locked() if sims else 1.0
        # active_count is the projected crowd (slider) + live phones, not agent structs.
        projected = int(round(sims * weight)) + phones if self.enabled else phones
        return {
            "enabled": self.enabled,
            "anti_gridlock": self.anti_gridlock,
            "simulated_count": self.simulated_count,
            "real_count": phones,
            "active_count": projected,
            "projection_agents": sims,
            "projection_weight": round(weight, 2),
            "metrics": self._metrics.as_dict(),
            "compare": self._compare,
            "last_rebalance_sim_min": None if self._last_rebalance_sim < 0 else int(self._last_rebalance_sim),
        }

    def status(self) -> dict:
        with self._lock:
            return self.status_locked()

    # ----- BPR / weights -----

    def factors(self) -> np.ndarray:
        with self._lock:
            if self._rg is None or not self.enabled:
                return np.ones(0)
            return bpr_factor(self._volume, self._capacity)

    def apply_journey_weights(self, journey_graph) -> None:
        """Scale a JourneyGraph's free-flow weights by parent-edge BPR factors."""
        if not self.enabled or self._rg is None:
            return
        with self._lock:
            factors = bpr_factor(self._volume, self._capacity)
            parent = journey_graph.parent
            # parent indexes into base RoadGraph edges.
            scale = factors[np.clip(parent, 0, len(factors) - 1)]
            free = journey_graph.edge_len_m / 1000.0 / SPEED_KM_PER_MIN
            journey_graph.edge_weight = free * scale

    def travel_min_for_edges(self, edge_ids) -> float:
        """Congested travel minutes along base RoadGraph edge indices."""
        with self._lock:
            return self._travel_min_unlocked(edge_ids)

    def free_min_for_edges(self, edge_ids) -> float:
        if self._rg is None or not len(edge_ids):
            return 0.0
        ids = np.asarray(edge_ids, dtype=np.int64)
        return float(self._rg.edge_time_min[ids].sum())

    # ----- crowd -----

    def sync_phones(self, evacuees: dict) -> None:
        """Treat live phone heartbeats as cars (one each)."""
        with self._lock:
            if self._rg is None:
                return
            live = set()
            for eid, row in evacuees.items():
                live.add(eid)
                agent = self._agents.get(eid)
                if agent is None:
                    self._agents[eid] = Agent(
                        id=eid, lat=float(row["lat"]), lon=float(row["lon"]), kind="phone",
                    )
                else:
                    agent.lat = float(row["lat"])
                    agent.lon = float(row["lon"])
                    agent.arrived = False
            # Drop phones that went stale (no longer in the map).
            for eid in list(self._agents):
                if self._agents[eid].kind == "phone" and eid not in live:
                    self._unload_agent_locked(self._agents.pop(eid))
            if self.enabled:
                self._ensure_crowd_locked()

    def _ensure_crowd_locked(self) -> None:
        sims = [a for a in self._agents.values() if a.kind == "sim"]
        target = min(int(self.simulated_count), MAX_SIM_AGENTS)
        while len(sims) > target:
            gone = sims.pop()
            self._unload_agent_locked(self._agents.pop(gone.id))
        need = target - len(sims)
        if need <= 0 or self._rg is None:
            return
        # Prefer nodes within ~4 km of the hazard so corridors actually jam.
        rg = self._rg
        dist = np.hypot(
            (rg.node_lat - self.cluster_lat) * 111_320.0,
            (rg.node_lon - self.cluster_lon) * 111_320.0 * max(0.2, abs(math.cos(math.radians(self.cluster_lat)))),
        )
        near = np.flatnonzero(dist <= 4000.0)
        if len(near) < 8:
            near = np.argsort(dist)[: max(8, min(200, rg.n_nodes))]
        picks = self._rng.choice(near, size=need, replace=True)
        for i, idx in enumerate(picks):
            lat = float(rg.node_lat[idx])
            lon = float(rg.node_lon[idx])
            jitter = (i % 97) * 1e-5
            aid = f"sim_{len(self._agents)}_{int(idx)}_{i}"
            self._agents[aid] = Agent(
                id=aid, lat=lat + jitter, lon=lon + jitter * 0.5, kind="sim",
            )

    def _unload_agent_locked(self, agent: Agent) -> None:
        w = float(agent.load_weight or 1.0)
        if agent.edge_ids:
            for e in agent.edge_ids:
                if 0 <= e < len(self._volume):
                    self._volume[e] = max(0.0, self._volume[e] - w)
        agent.edge_ids = ()
        agent.route_id = None
        agent.shelter_id = None
        agent.load_weight = 1.0

    def _load_agent_locked(self, agent: Agent, edge_ids, route_id, shelter_id,
                           eta_min, free_eta_min, sim_time: int) -> None:
        self._unload_agent_locked(agent)
        ids = tuple(int(e) for e in edge_ids)
        weight = 1.0 if agent.kind == "phone" else self._projection_weight_locked()
        agent.edge_ids = ids
        agent.route_id = route_id
        agent.shelter_id = shelter_id
        agent.eta_min = float(eta_min)
        agent.free_eta_min = float(free_eta_min)
        agent.assigned_sim_min = int(sim_time)
        agent.load_weight = float(weight)
        for e in ids:
            if 0 <= e < len(self._volume):
                self._volume[e] += weight

    # ----- assignment -----

    def on_sim_tick(self, sim_time: int) -> None:
        if not self.enabled or self._rg is None:
            return
        with self._lock:
            self._ensure_crowd_locked()
            if not self._agents:
                return
            if sim_time - self._last_rebalance_sim >= REBALANCE_EVERY_MIN or self._last_rebalance_sim < 0:
                self._schedule_assign_locked(force=False, sim_time=sim_time)

    def rebalance_now(self, sim_time: int = 0) -> dict:
        with self._lock:
            if self.enabled and self._rg is not None:
                self._ensure_crowd_locked()
                self._schedule_assign_locked(force=True, sim_time=sim_time)
            return self.status_locked()

    def _assign_all_locked(self, force: bool = False, sim_time: int = 0) -> None:
        agents = [a for a in self._agents.values() if not a.arrived]
        if not agents:
            self._recompute_metrics_locked()
            return

        if self.anti_gridlock:
            if force or any(not a.edge_ids for a in agents):
                for a in agents:
                    self._unload_agent_locked(a)
                order = sorted(agents, key=lambda a: (a.kind != "phone", a.lat + a.lon))
                # Unique BPR-aware routes for a capped set of leaders; followers clone
                # so we paint volume without 250 full Dijkstras every click.
                leaders = order[:MAX_UNIQUE_ROUTES]
                followers = order[MAX_UNIQUE_ROUTES:]
                leader_picks = []
                for agent in leaders:
                    pick = self._pick_route_fast_locked(agent.lat, agent.lon)
                    if pick is None:
                        continue
                    self._load_agent_locked(
                        agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                        pick["eta_min"], pick["free_eta_min"], sim_time,
                    )
                    leader_picks.append(pick)
                if leader_picks:
                    for i, agent in enumerate(followers):
                        pick = leader_picks[i % len(leader_picks)]
                        self._load_agent_locked(
                            agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                            pick["eta_min"], pick["free_eta_min"], sim_time,
                        )
            else:
                order = sorted(agents, key=lambda a: (a.kind != "phone", -a.eta_min))
                for agent in order[:MAX_UNIQUE_ROUTES]:
                    self._maybe_switch_locked(agent, sim_time)
        else:
            for a in agents:
                self._unload_agent_locked(a)
            seed = self._pick_route_fast_locked(agents[0].lat, agents[0].lon)
            for agent in agents:
                pick = seed
                if pick is None or not pick.get("edge_ids"):
                    pick = self._pick_route_fast_locked(agent.lat, agent.lon)
                if pick is None:
                    continue
                self._load_agent_locked(
                    agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                    pick["eta_min"], pick["free_eta_min"], sim_time,
                )
            for agent in agents:
                if not agent.edge_ids:
                    continue
                agent.eta_min = self._travel_min_unlocked(agent.edge_ids)
                agent.free_eta_min = self.free_min_for_edges(agent.edge_ids)
        self._recompute_metrics_locked()

    def _maybe_switch_locked(self, agent: Agent, sim_time: int) -> None:
        if not agent.edge_ids:
            pick = self._pick_route_fast_locked(agent.lat, agent.lon)
            if pick:
                self._load_agent_locked(
                    agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                    pick["eta_min"], pick["free_eta_min"], sim_time,
                )
            return
        old_edges = agent.edge_ids
        old_route = agent.route_id
        old_shelter = agent.shelter_id
        old_free = agent.free_eta_min
        current_eta = self._travel_min_unlocked(old_edges)
        self._unload_agent_locked(agent)
        pick = self._pick_route_fast_locked(agent.lat, agent.lon)
        if pick is None:
            self._load_agent_locked(
                agent, old_edges, old_route, old_shelter, current_eta, old_free, sim_time,
            )
            return
        saves = current_eta - pick["eta_min"]
        cooled = (sim_time - agent.last_switch_sim_min) >= SWITCH_COOLDOWN_MIN
        if (pick["route_id"] != old_route and saves >= SWITCH_SAVE_MIN and cooled):
            self._metrics.reroutes += 1
            agent.last_switch_sim_min = int(sim_time)
            self._load_agent_locked(
                agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                pick["eta_min"], pick["free_eta_min"], sim_time,
            )
        else:
            self._load_agent_locked(
                agent, old_edges, old_route, old_shelter, current_eta, old_free, sim_time,
            )

    def _travel_min_unlocked(self, edge_ids) -> float:
        if self._rg is None or not len(edge_ids):
            return 0.0
        ids = np.asarray(edge_ids, dtype=np.int64)
        free = self._rg.edge_time_min[ids]
        if not self.enabled:
            return float(free.sum())
        return float((free * bpr_factor(self._volume, self._capacity)[ids]).sum())

    def _pick_route_fast_locked(self, lat: float, lon: float) -> Optional[dict]:
        """BPR-weighted Dijkstra to the nearest open shelter — no full /route call."""
        rg = self._rg
        if rg is None or rg.n_nodes == 0:
            return None
        start, _ = rg.nearest_node(lat, lon)
        if self.enabled and len(self._volume) == rg.n_edges:
            weights = rg.edge_time_min * bpr_factor(self._volume, self._capacity)
        else:
            weights = rg.edge_time_min
        tree = shortest_paths(
            rg.n_nodes, rg.edge_u, rg.edge_v, weights, start, rg.edge_permitted,
        )
        shelters = self._shelters_fn() if self._shelters_fn else []
        best = None
        for shelter in shelters:
            props = shelter.get("properties") or {}
            if not props.get("open", True):
                continue
            if props.get("occupancy", 0) >= props.get("capacity", 10**9):
                continue
            coords = shelter.get("geometry", {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            end, _ = rg.nearest_node(float(coords[1]), float(coords[0]))
            dist = float(tree.distance[end])
            if not math.isfinite(dist):
                continue
            edges = tree.edges_to(start, end)
            if edges is None:
                continue
            if best is None or dist < best[0]:
                best = (dist, shelter, edges)
        if best is None:
            return None
        dist, shelter, edges = best
        edge_ids = [int(e) for e in edges]
        free = float(rg.edge_time_min[np.asarray(edge_ids, dtype=np.int64)].sum()) if edge_ids else 0.0
        sid = shelter["id"]
        eta = _sane_minutes(dist)
        return {
            "route_id": f"rt_{sid}_fastest",
            "shelter_id": sid,
            "edge_ids": edge_ids,
            "eta_min": eta,
            "free_eta_min": free,
            "delay_min": max(0.0, eta - free),
        }

    def _pick_route_locked(self, lat: float, lon: float) -> Optional[dict]:
        """Compat alias — crowd assignment always uses the fast graph path."""
        return self._pick_route_fast_locked(lat, lon)

    def _recompute_metrics_locked(self) -> None:
        active = [a for a in self._agents.values() if not a.arrived and a.edge_ids]
        arrived = sum(1 for a in self._agents.values() if a.arrived)
        if not active:
            self._metrics = TrafficMetrics(
                clearance_min=0.0, avg_eta_min=0.0, max_vc=0.0, jammed_edges=0,
                agents_active=0, agents_arrived=arrived, reroutes=self._metrics.reroutes,
            )
            return
        etas = [_sane_minutes(a.eta_min) for a in active]
        vc = self._volume / np.maximum(self._capacity, 1.0) if len(self._volume) else np.zeros(0)
        raw_max_vc = float(vc.max()) if len(vc) else 0.0
        projected = int(round(sum(float(a.load_weight or 1.0) for a in active)))
        self._metrics = TrafficMetrics(
            clearance_min=float(max(etas)),
            avg_eta_min=float(sum(etas) / len(etas)),
            # Report real pressure but clamp so "Peak load 5473%" never ships.
            max_vc=float(min(raw_max_vc, MAX_VC_REPORT)),
            jammed_edges=int(np.sum(vc >= 0.9)),
            agents_active=projected,
            agents_arrived=arrived,
            reroutes=self._metrics.reroutes,
        )

    # ----- compare -----

    def compare(self, sim_time: int = 0) -> dict:
        """Run naive vs anti-gridlock assignment and return clearance times."""
        with self._lock:
            if self._rg is None:
                return {"error": "traffic_unavailable", "message": "Road graph not ready"}
            was_enabled = self.enabled
            was_anti = self.anti_gridlock
            self.enabled = True
            self._ensure_crowd_locked()

            self.anti_gridlock = False
            self._assign_all_locked(force=True, sim_time=sim_time)
            without = _sane_minutes(self._metrics.clearance_min)

            self.anti_gridlock = True
            self._assign_all_locked(force=True, sim_time=sim_time)
            with_ag = _sane_minutes(self._metrics.clearance_min)

            self._compare = {
                "without_min": round(without, 1),
                "with_min": round(with_ag, 1),
                "saved_min": round(without - with_ag, 1),
                "label": f"Clearance time {without:.0f} → {with_ag:.0f} min",
            }
            self.enabled = was_enabled
            self.anti_gridlock = True if was_enabled else was_anti
            if self.enabled:
                self.anti_gridlock = True
                self._assign_all_locked(force=True, sim_time=sim_time)
            else:
                self.anti_gridlock = was_anti
                self._volume[:] = 0
            return {"ok": True, **self._compare, **self.status_locked()}

    # ----- map payload -----

    def _traffic_level(self, ratio: float) -> str:
        if ratio < 0.9:
            return "busy"
        if ratio < 1.3:
            return "jammed"
        return "gridlock"

    def _node_edge_index_locked(self) -> list[list[int]]:
        """Undirected adjacency: node → incident edge ids (built once per graph)."""
        rg = self._rg
        cached = getattr(self, "_node_edges", None)
        if cached is not None and getattr(self, "_node_edges_n", 0) == rg.n_edges:
            return cached
        buckets: list[list[int]] = [[] for _ in range(rg.n_nodes)]
        for e in range(rg.n_edges):
            buckets[int(rg.edge_u[e])].append(e)
            buckets[int(rg.edge_v[e])].append(e)
        self._node_edges = buckets
        self._node_edges_n = rg.n_edges
        return buckets

    def _expand_corridor_edges_locked(self, seeds: list[int], vc: np.ndarray) -> list[int]:
        """Grow from congested seeds; keep connectors + reverse lanes so ribbons don't break."""
        if not seeds:
            return []
        node_edges = self._node_edge_index_locked()
        rg = self._rg
        # Undirected pair → both directed edges (fills opposite-lane holes).
        pair_to_edges: dict[tuple[int, int], list[int]] = {}
        for e in range(rg.n_edges):
            a, b = int(rg.edge_u[e]), int(rg.edge_v[e])
            key = (a, b) if a <= b else (b, a)
            pair_to_edges.setdefault(key, []).append(e)

        chosen = set(int(e) for e in seeds)
        # Always include the reverse direction of every seed.
        for e in list(chosen):
            a, b = int(rg.edge_u[e]), int(rg.edge_v[e])
            key = (a, b) if a <= b else (b, a)
            for sib in pair_to_edges.get(key, ()):
                chosen.add(sib)

        queue = list(chosen)
        while queue and len(chosen) < MAP_EDGE_LIMIT:
            e = queue.pop()
            for node in (int(rg.edge_u[e]), int(rg.edge_v[e])):
                incident = node_edges[node]
                # If this node already has corridor traffic, keep every incident
                # edge that carries any cars — closes intersection gaps.
                node_hot = any(
                    (x in chosen) or self._volume[x] >= MAP_FILL_MIN_VOLUME or float(vc[x]) >= MAP_MIN_VC * 0.5
                    for x in incident
                )
                for nxt in incident:
                    if nxt in chosen:
                        continue
                    keep = (
                        self._volume[nxt] >= MAP_FILL_MIN_VOLUME
                        or float(vc[nxt]) >= MAP_MIN_VC * 0.5
                        or (node_hot and self._volume[nxt] > 0)
                    )
                    if not keep:
                        continue
                    chosen.add(nxt)
                    a, b = int(rg.edge_u[nxt]), int(rg.edge_v[nxt])
                    key = (a, b) if a <= b else (b, a)
                    for sib in pair_to_edges.get(key, ()):
                        if sib not in chosen:
                            chosen.add(sib)
                            queue.append(sib)
                    queue.append(nxt)
                    if len(chosen) >= MAP_EDGE_LIMIT:
                        break
        return list(chosen)

    def _edge_poly_from_node_locked(self, e: int, from_node: int) -> tuple[list[list[float]], int]:
        """Polyline for edge e starting at from_node, endpoints snapped to node lat/lon."""
        rg = self._rg
        u, v = int(rg.edge_u[e]), int(rg.edge_v[e])
        coords = rg.edge_coords_ll(e).tolist()
        if from_node == v:
            coords = list(reversed(coords))
            to_node = u
        else:
            to_node = v
        # Snap ends to shared node coordinates so chains join with zero gaps.
        coords[0] = [float(rg.node_lon[from_node]), float(rg.node_lat[from_node])]
        coords[-1] = [float(rg.node_lon[to_node]), float(rg.node_lat[to_node])]
        return coords, to_node

    def _merge_corridor_features_locked(self, edge_ids: list[int], vc: np.ndarray,
                                        factors: np.ndarray) -> list[dict]:
        """Chain connected edges into longer LineStrings so traffic reads continuous."""
        if not edge_ids:
            return []
        rg = self._rg
        remaining = set(int(e) for e in edge_ids)
        at_node: dict[int, list[int]] = {}
        for e in remaining:
            at_node.setdefault(int(rg.edge_u[e]), []).append(e)
            at_node.setdefault(int(rg.edge_v[e]), []).append(e)

        def detach(e: int) -> None:
            remaining.discard(e)
            for n in (int(rg.edge_u[e]), int(rg.edge_v[e])):
                bucket = at_node.get(n)
                if bucket and e in bucket:
                    bucket.remove(e)

        def pick_next(tip: int, prefer_name: str) -> Optional[int]:
            candidates = [e for e in at_node.get(tip, []) if e in remaining]
            if not candidates:
                return None
            candidates.sort(
                key=lambda e: (0 if rg.edge_name[e] == prefer_name else 1, -float(vc[e])),
            )
            return candidates[0]

        def grow(tip: int, chain: list[int], coords: list, forward: bool) -> None:
            while True:
                prefer = rg.edge_name[chain[-1] if forward else chain[0]]
                nxt = pick_next(tip, prefer)
                if nxt is None:
                    return
                detach(nxt)
                piece, tip = self._edge_poly_from_node_locked(nxt, tip)
                if forward:
                    # Shared node already at coords[-1] == piece[0].
                    coords.extend(piece[1:])
                    chain.append(nxt)
                else:
                    # Growing backward: piece runs away from seed; prepend reversed.
                    prefix = list(reversed(piece))
                    coords[:0] = prefix[:-1]
                    chain.insert(0, nxt)

        features: list[dict] = []
        feat_i = 0
        while remaining:
            start_e = next(iter(remaining))
            for e in list(remaining):
                deg_u = len(at_node.get(int(rg.edge_u[e]), []))
                deg_v = len(at_node.get(int(rg.edge_v[e]), []))
                if deg_u <= 1 or deg_v <= 1:
                    start_e = e
                    break
            u, v = int(rg.edge_u[start_e]), int(rg.edge_v[start_e])
            detach(start_e)
            chain = [start_e]
            coords, _ = self._edge_poly_from_node_locked(start_e, u)
            grow(v, chain, coords, forward=True)
            grow(u, chain, coords, forward=False)

            ratios = [float(vc[e]) for e in chain]
            ratio = max(ratios) if ratios else 0.0
            level = self._traffic_level(ratio)
            vol = float(sum(float(self._volume[e]) for e in chain))
            name = rg.edge_name[chain[0]]
            features.append({
                "type": "Feature",
                "id": f"tr_c_{feat_i}",
                "properties": {
                    "edge": int(chain[0]),
                    "edges": len(chain),
                    "name": name,
                    "highway": self._highway[chain[0]] if chain[0] < len(self._highway) else "road",
                    "lanes": int(self._lanes[chain[0]]) if chain[0] < len(self._lanes) else 1,
                    "volume": round(vol, 1),
                    "capacity": round(float(self._capacity[chain[0]]), 1),
                    "vc_ratio": round(ratio, 2),
                    "level": level,
                    "free_min": round(float(sum(rg.edge_time_min[e] for e in chain)), 3),
                    "travel_min": round(float(sum(rg.edge_time_min[e] * factors[e] for e in chain)), 3),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            })
            feat_i += 1

        # Second pass: stitch ribbons whose endpoints sit on the same graph node /
        # nearly the same lon-lat so leftover gaps at T-junctions disappear.
        return self._stitch_nearby_features_locked(features)

    def _stitch_nearby_features_locked(self, features: list[dict]) -> list[dict]:
        if len(features) < 2:
            return features
        # Index endpoints (rounded) → feature indices still alive.
        alive = list(range(len(features)))
        coords_of = [list(f["geometry"]["coordinates"]) for f in features]
        level_rank = {"busy": 1, "jammed": 2, "gridlock": 3}

        def end_key(pt, kind: str):
            return (kind, round(pt[0], 5), round(pt[1], 5))

        changed = True
        while changed:
            changed = False
            index: dict[tuple, list[tuple[int, str]]] = {}
            for i in alive:
                c = coords_of[i]
                if len(c) < 2:
                    continue
                index.setdefault(end_key(c[0], "s"), []).append((i, "s"))
                index.setdefault(end_key(c[-1], "e"), []).append((i, "e"))
            for bucket in index.values():
                if len(bucket) < 2:
                    continue
                # Pair first two distinct features that touch here.
                (i, ei), (j, ej) = bucket[0], bucket[1]
                if i == j or i not in alive or j not in alive:
                    continue
                a, b = coords_of[i], coords_of[j]
                # Orient so a runs into b.
                if ei == "e" and ej == "s":
                    merged = a + b[1:]
                elif ei == "s" and ej == "e":
                    merged = b + a[1:]
                elif ei == "e" and ej == "e":
                    merged = a + list(reversed(b))[1:]
                else:  # s + s
                    merged = list(reversed(a)) + b[1:]
                # Keep i, drop j.
                coords_of[i] = merged
                props_i = features[i]["properties"]
                props_j = features[j]["properties"]
                props_i["edges"] = int(props_i.get("edges", 1)) + int(props_j.get("edges", 1))
                props_i["volume"] = round(float(props_i.get("volume", 0)) + float(props_j.get("volume", 0)), 1)
                if level_rank.get(props_j.get("level"), 0) > level_rank.get(props_i.get("level"), 0):
                    props_i["level"] = props_j["level"]
                    props_i["vc_ratio"] = props_j.get("vc_ratio", props_i.get("vc_ratio"))
                features[i]["geometry"]["coordinates"] = merged
                alive.remove(j)
                changed = True
                break

        return [features[i] for i in alive]

    def edge_features(self, limit: int = MAP_EDGE_LIMIT) -> dict:
        with self._lock:
            if self._rg is None:
                return {"type": "FeatureCollection", "features": []}
            if not self.enabled:
                return {"type": "FeatureCollection", "features": []}
            rg = self._rg
            factors = bpr_factor(self._volume, self._capacity)
            vc = self._volume / np.maximum(self._capacity, 1.0)
            hwy_bonus = np.zeros(rg.n_edges, dtype=np.float64)
            for i, hwy in enumerate(self._highway):
                if hwy in ("motorway", "trunk", "primary"):
                    hwy_bonus[i] = 0.35
                elif hwy in ("secondary", "tertiary"):
                    hwy_bonus[i] = 0.15
            score = vc + (self._volume > 0).astype(np.float64) + hwy_bonus
            order = np.argsort(-score)
            seeds: list[int] = []
            for idx in order:
                if len(seeds) >= MAP_SEED_LIMIT:
                    break
                if float(vc[idx]) < MAP_MIN_VC or self._volume[idx] <= 0:
                    continue
                seeds.append(int(idx))
            edge_ids = self._expand_corridor_edges_locked(seeds, vc)
            if len(edge_ids) > limit:
                edge_ids = sorted(edge_ids, key=lambda e: -float(score[e]))[: int(limit)]
            features = self._merge_corridor_features_locked(edge_ids, vc, factors)
            return {"type": "FeatureCollection", "features": features}

    def payload(self) -> dict:
        with self._lock:
            body = self.status_locked()
            body["edges"] = self.edge_features()
            return body

    def annotate_option(self, option: dict, journey_graph, edge_indices) -> dict:
        """Add traffic fields onto a /route option (additive)."""
        if journey_graph is None or not len(edge_indices):
            option["traffic_delay_min"] = 0
            option["traffic_free_min"] = option.get("modeled_duration_min")
            option["_traffic_edge_ids"] = []
            return option
        parent = [int(journey_graph.parent[int(e)]) for e in edge_indices]
        free = self.free_min_for_edges(parent)
        congested = self.travel_min_for_edges(parent) if self.enabled else free
        delay = max(0.0, congested - free)
        option["traffic_delay_min"] = int(round(delay))
        option["traffic_free_min"] = round(free, 2)
        option["_traffic_edge_ids"] = parent
        if self.enabled and delay >= 1:
            # Keep eta_min / modeled_duration reflecting congestion when traffic is on.
            option["modeled_duration_min"] = round(congested, 2)
            option["eta_min"] = int(math.ceil(congested - 1e-9))
        return option

    def faster_route_hint(self, lat: float, lon: float, current_route_id: Optional[str],
                          sim_time: int = 0) -> Optional[dict]:
        """Phone banner / auto-reroute: faster route available, saves N min."""
        if not self.enabled or not current_route_id:
            return None
        with self._lock:
            pick = self._pick_route_locked(lat, lon)
            if pick is None or pick["route_id"] == current_route_id:
                return None
            # Prefer the caller's phone pin, then any car already on that route.
            agent = next(
                (
                    a for a in self._agents.values()
                    if a.route_id == current_route_id and abs(a.lat - lat) < 2e-3 and abs(a.lon - lon) < 2e-3
                ),
                None,
            )
            if agent is None:
                agent = next((a for a in self._agents.values() if a.route_id == current_route_id), None)
            if agent is not None:
                current_eta = float(agent.eta_min)
            else:
                # Judge phones may not be on a crowd corridor yet — cost the free-flow
                # path to their current shelter under live BPR, then compare to pick.
                sid = None
                if current_route_id.startswith("rt_") and current_route_id.endswith("_fastest"):
                    sid = current_route_id[len("rt_"):-len("_fastest")]
                current_eta = None
                if sid and self._shelters_fn:
                    for shelter in self._shelters_fn():
                        if shelter.get("id") != sid:
                            continue
                        coords = shelter.get("geometry", {}).get("coordinates")
                        if not coords or len(coords) < 2:
                            break
                        rg = self._rg
                        if rg is None:
                            break
                        start, _ = rg.nearest_node(lat, lon)
                        end, _ = rg.nearest_node(float(coords[1]), float(coords[0]))
                        tree = shortest_paths(
                            rg.n_nodes, rg.edge_u, rg.edge_v, rg.edge_time_min,
                            start, rg.edge_permitted,
                        )
                        edges = tree.edges_to(start, end)
                        if edges is not None:
                            current_eta = self._travel_min_unlocked([int(e) for e in edges])
                        break
                if current_eta is None:
                    return None
            saves = current_eta - pick["eta_min"]
            if saves < SWITCH_SAVE_MIN:
                return None
            mins = max(1, int(round(saves)))
            return {
                "route_id": pick["route_id"],
                "shelter_id": pick["shelter_id"],
                "saves_min": mins,
                "message": f"Faster route available, saves {mins} min",
                "reason": "traffic",
            }


# Process-wide engine (bound at load_graph / API startup).
engine = TrafficEngine()
