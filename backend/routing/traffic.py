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

from backend.routing.road_graph import SPEED_KM_PER_MIN, RoadGraph

log = logging.getLogger(__name__)

# BPR (Bureau of Public Roads) — standard volume-delay.
BPR_ALPHA = 0.15
BPR_BETA = 4.0

# Static loading capacity (vehicles that can share an edge before it jams).
# Tuned for demo N≈50–500, not real hourly freeway flow.
# Per-lane static loading capacity (cars sharing an edge before it jams). Kept
# intentionally low so a few hundred evacuating cars can create visible gridlock.
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

REBALANCE_EVERY_MIN = 5
SWITCH_SAVE_MIN = 3.0
SWITCH_COOLDOWN_MIN = 10
DEFAULT_SIMULATED = 80
MAX_SIMULATED = 500
# How many congested edges to return for the dashboard map (sorted by v/c).
MAP_EDGE_LIMIT = 2500


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
    """t / t0 = 1 + α (v/c)^β. Capacity floored so empty edges stay free-flow."""
    c = np.maximum(capacity.astype(np.float64), 1.0)
    vc = np.maximum(volume.astype(np.float64), 0.0) / c
    return 1.0 + BPR_ALPHA * np.power(vc, BPR_BETA)


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
        self._route_fn = None  # set by API: (lat, lon) -> route body
        self._shelters_fn = None
        # Spawn cluster centre (hazard origin). Defaults to central Edmonton.
        self.cluster_lat = 53.5461
        self.cluster_lon = -113.4938

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
                self._assign_all_locked(force=True)
            elif not self.enabled:
                self._volume[:] = 0
                self._metrics = TrafficMetrics()
            return self.status_locked()

    def status_locked(self) -> dict:
        phones = sum(1 for a in self._agents.values() if a.kind == "phone" and not a.arrived)
        sims = sum(1 for a in self._agents.values() if a.kind == "sim" and not a.arrived)
        return {
            "enabled": self.enabled,
            "anti_gridlock": self.anti_gridlock,
            "simulated_count": self.simulated_count,
            "real_count": phones,
            "active_count": phones + sims,
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
        while len(sims) > self.simulated_count:
            gone = sims.pop()
            self._unload_agent_locked(self._agents.pop(gone.id))
        need = self.simulated_count - len(sims)
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
        if agent.edge_ids:
            for e in agent.edge_ids:
                if 0 <= e < len(self._volume):
                    self._volume[e] = max(0.0, self._volume[e] - 1.0)
        agent.edge_ids = ()
        agent.route_id = None
        agent.shelter_id = None

    def _load_agent_locked(self, agent: Agent, edge_ids, route_id, shelter_id,
                           eta_min, free_eta_min, sim_time: int) -> None:
        self._unload_agent_locked(agent)
        ids = tuple(int(e) for e in edge_ids)
        agent.edge_ids = ids
        agent.route_id = route_id
        agent.shelter_id = shelter_id
        agent.eta_min = float(eta_min)
        agent.free_eta_min = float(free_eta_min)
        agent.assigned_sim_min = int(sim_time)
        for e in ids:
            if 0 <= e < len(self._volume):
                self._volume[e] += 1.0

    # ----- assignment -----

    def on_sim_tick(self, sim_time: int) -> None:
        if not self.enabled or self._rg is None or self._route_fn is None:
            return
        with self._lock:
            self._ensure_crowd_locked()
            if not self._agents:
                return
            if sim_time - self._last_rebalance_sim >= REBALANCE_EVERY_MIN or self._last_rebalance_sim < 0:
                self._assign_all_locked(force=False, sim_time=sim_time)
                self._last_rebalance_sim = int(sim_time)

    def rebalance_now(self, sim_time: int = 0) -> dict:
        with self._lock:
            if self.enabled and self._rg is not None:
                self._ensure_crowd_locked()
                self._assign_all_locked(force=True, sim_time=sim_time)
                self._last_rebalance_sim = int(sim_time)
            return self.status_locked()

    def _assign_all_locked(self, force: bool = False, sim_time: int = 0) -> None:
        if self._route_fn is None:
            return
        agents = [a for a in self._agents.values() if not a.arrived]
        if not agents:
            self._recompute_metrics_locked()
            return

        if self.anti_gridlock:
            if force or any(not a.edge_ids for a in agents):
                # Cold start: load cars one-at-a-time so each sees the jam forming.
                for a in agents:
                    self._unload_agent_locked(a)
                order = sorted(agents, key=lambda a: (a.kind != "phone", a.lat + a.lon))
                for agent in order:
                    pick = self._pick_route_locked(agent.lat, agent.lon)
                    if pick is None:
                        continue
                    self._load_agent_locked(
                        agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                        pick["eta_min"], pick["free_eta_min"], sim_time,
                    )
            else:
                # Periodic rebalance: switch only when it saves SWITCH_SAVE_MIN + cooldown.
                order = sorted(agents, key=lambda a: (a.kind != "phone", -a.eta_min))
                for agent in order:
                    self._maybe_switch_locked(agent, sim_time)
        else:
            # Naive gridlock: assign everyone against an empty map, then dump on at once.
            for a in agents:
                self._unload_agent_locked(a)
            scratch = []
            for agent in agents:
                scratch.append((agent, self._pick_route_locked(agent.lat, agent.lon)))
            for agent, pick in scratch:
                if pick is None:
                    continue
                self._load_agent_locked(
                    agent, pick["edge_ids"], pick["route_id"], pick["shelter_id"],
                    pick["eta_min"], pick["free_eta_min"], sim_time,
                )
            for agent, pick in scratch:
                if pick is None or not agent.edge_ids:
                    continue
                agent.eta_min = self._travel_min_unlocked(agent.edge_ids)
                agent.free_eta_min = self.free_min_for_edges(agent.edge_ids)
        self._recompute_metrics_locked()

    def _maybe_switch_locked(self, agent: Agent, sim_time: int) -> None:
        if not agent.edge_ids:
            pick = self._pick_route_locked(agent.lat, agent.lon)
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
        # Peek at an alternate with this car removed from its current roads.
        self._unload_agent_locked(agent)
        pick = self._pick_route_locked(agent.lat, agent.lon)
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

    def _pick_route_locked(self, lat: float, lon: float) -> Optional[dict]:
        """Ask the live router for a best option; map journey edges → base edges."""
        try:
            body = self._route_fn(lat, lon)
        except Exception as exc:  # noqa: BLE001 — crowd must not kill the sim loop
            log.debug("traffic route failed: %s", exc)
            return None
        if not body:
            return None
        best_id = body.get("best_route_id")
        options = body.get("options") or []
        opt = next((o for o in options if o.get("id") == best_id), None)
        if opt is None and options:
            opt = next((o for o in options if o.get("status") in ("ok", "tight")), options[0])
        if opt is None:
            return None
        edge_ids = opt.get("_traffic_edge_ids") or ()
        eta = float(opt.get("modeled_duration_min") or opt.get("eta_min") or 0)
        free = float(opt.get("traffic_free_min") or eta)
        delay = max(0.0, eta - free)
        return {
            "route_id": opt.get("id"),
            "shelter_id": opt.get("shelter_id"),
            "edge_ids": edge_ids,
            "eta_min": eta,
            "free_eta_min": free,
            "delay_min": delay,
        }

    def _recompute_metrics_locked(self) -> None:
        active = [a for a in self._agents.values() if not a.arrived and a.edge_ids]
        arrived = sum(1 for a in self._agents.values() if a.arrived)
        if not active:
            self._metrics = TrafficMetrics(
                clearance_min=0.0, avg_eta_min=0.0, max_vc=0.0, jammed_edges=0,
                agents_active=0, agents_arrived=arrived, reroutes=self._metrics.reroutes,
            )
            return
        etas = [a.eta_min for a in active]
        vc = self._volume / np.maximum(self._capacity, 1.0) if len(self._volume) else np.zeros(0)
        self._metrics = TrafficMetrics(
            clearance_min=float(max(etas)),
            avg_eta_min=float(sum(etas) / len(etas)),
            max_vc=float(vc.max()) if len(vc) else 0.0,
            jammed_edges=int(np.sum(vc >= 0.9)),
            agents_active=len(active),
            agents_arrived=arrived,
            reroutes=self._metrics.reroutes,
        )

    # ----- compare -----

    def compare(self, sim_time: int = 0) -> dict:
        """Run naive vs anti-gridlock assignment and return clearance times."""
        with self._lock:
            if self._rg is None or self._route_fn is None:
                return {"error": "traffic_unavailable", "message": "Road graph or router not ready"}
            was_enabled = self.enabled
            was_anti = self.anti_gridlock
            self.enabled = True
            self._ensure_crowd_locked()

            self.anti_gridlock = False
            self._assign_all_locked(force=True, sim_time=sim_time)
            without = self._metrics.clearance_min

            self.anti_gridlock = True
            self._assign_all_locked(force=True, sim_time=sim_time)
            with_ag = self._metrics.clearance_min

            self._compare = {
                "without_min": None if without is None else round(without, 1),
                "with_min": None if with_ag is None else round(with_ag, 1),
                "saved_min": None if without is None or with_ag is None else round(without - with_ag, 1),
                "label": (
                    f"Clearance time {without:.0f} → {with_ag:.0f} min"
                    if without is not None and with_ag is not None else None
                ),
            }
            # Leave anti-gridlock on (the "after" state) and restore enabled flag.
            self.anti_gridlock = True if was_enabled else was_anti
            self.enabled = was_enabled
            if self.enabled:
                self.anti_gridlock = True
                self._assign_all_locked(force=True, sim_time=sim_time)
            else:
                self.anti_gridlock = was_anti
                self._volume[:] = 0
            return {"ok": True, **self._compare, **self.status_locked()}

    # ----- map payload -----

    def edge_features(self, limit: int = MAP_EDGE_LIMIT) -> dict:
        with self._lock:
            if self._rg is None:
                return {"type": "FeatureCollection", "features": []}
            rg = self._rg
            factors = bpr_factor(self._volume, self._capacity) if self.enabled else np.ones(rg.n_edges)
            vc = self._volume / np.maximum(self._capacity, 1.0)
            # Prefer edges that actually have cars, then by v/c.
            score = vc + (self._volume > 0).astype(np.float64)
            order = np.argsort(-score)
            features = []
            for idx in order[:limit]:
                if not self.enabled and self._volume[idx] <= 0:
                    continue
                if self.enabled and self._volume[idx] <= 0 and vc[idx] < 0.05:
                    # Skip empty quiet edges to keep the payload small.
                    continue
                coords = rg.edge_coords_ll(int(idx)).tolist()
                if len(coords) < 2:
                    continue
                ratio = float(vc[idx])
                if ratio < 0.5:
                    level = "free"
                elif ratio < 0.9:
                    level = "busy"
                elif ratio < 1.3:
                    level = "jammed"
                else:
                    level = "gridlock"
                free = float(rg.edge_time_min[idx])
                features.append({
                    "type": "Feature",
                    "id": f"tr_{idx}",
                    "properties": {
                        "edge": int(idx),
                        "name": rg.edge_name[idx],
                        "highway": self._highway[idx] if idx < len(self._highway) else "road",
                        "lanes": int(self._lanes[idx]) if idx < len(self._lanes) else 1,
                        "volume": round(float(self._volume[idx]), 1),
                        "capacity": round(float(self._capacity[idx]), 1),
                        "vc_ratio": round(ratio, 2),
                        "level": level,
                        "free_min": round(free, 3),
                        "travel_min": round(free * float(factors[idx]), 3),
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
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
        """Phone banner: faster route available, saves N min."""
        if not self.enabled or not current_route_id:
            return None
        with self._lock:
            pick = self._pick_route_locked(lat, lon)
            if pick is None or pick["route_id"] == current_route_id:
                return None
            agent = next((a for a in self._agents.values()
                          if a.route_id == current_route_id and abs(a.lat - lat) < 1e-4), None)
            current_eta = agent.eta_min if agent else None
            if current_eta is None:
                return None
            saves = current_eta - pick["eta_min"]
            if saves < SWITCH_SAVE_MIN:
                return None
            return {
                "route_id": pick["route_id"],
                "shelter_id": pick["shelter_id"],
                "saves_min": int(round(saves)),
                "message": f"Faster route available, saves {int(round(saves))} min",
                "reason": "traffic",
            }


# Process-wide engine (bound at load_graph / API startup).
engine = TrafficEngine()
