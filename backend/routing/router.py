"""GET /route: 2-4 road routes from the pin, each checked against the fire forecast.

Loads the saved Edmonton road graph once (never downloads) and answers with the
route shape in shared/contract.md. Unsafe routes are kept and marked; routes
are not a safety guarantee. ETAs are illustrative at a flat 30 km/h.
"""

from math import ceil, floor, isfinite
import gzip
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import weakref

import numpy as np
import osmnx as ox

from backend.routing.candidates import (
    NoRouteError, Stats, build_candidates, straight_line_candidates,
)
from backend.routing.evac_zone import (
    danger_rings, mark_unsafe_shelters, unsafe_shelter_ids, zone_check,
)
from backend.routing.road_graph import CellTable, FireGrid, RoadGraph, build_cell_table
from backend.routing.safety import BUFFER_MIN, EdgeFire, t_label, viable
from backend.routing.select import rank_key, select
from backend.routing.traffic import engine as traffic_engine
from backend.sim.oracle import validation_error


ROUTING_DIR = Path(__file__).resolve().parent
GRAPH_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
GRAPH_GZ_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml.gz"
# West, south, east, north. Includes contract shelters; a bit larger than the
# downloaded graph so east/south pins still get backup routes instead of 404.
DEMO_BBOX = (-113.75, 53.40, -113.32, 53.62)
_graph = None
_backup_mode = False
BACKUP_WARNING = (
    "Road graph unavailable. Straight-line distance and ETA are estimates only, "
    "not navigation instructions or a verified safe driving route."
)


def _resolve_graph_path() -> Path:
    """Prefer SHEPHERD_GRAPH_PATH, then unpacked GraphML, then the shipped .gz."""
    saved_path = os.environ.get("SHEPHERD_GRAPH_PATH")
    if saved_path is not None:
        return Path(saved_path)
    if GRAPH_PATH.is_file():
        return GRAPH_PATH
    if GRAPH_GZ_PATH.is_file():
        return GRAPH_GZ_PATH
    return GRAPH_PATH


def _load_graphml(graph_path: Path):
    """Load GraphML from a plain or gzip-compressed file."""
    if graph_path.suffix == ".gz" or str(graph_path).endswith(".graphml.gz"):
        with gzip.open(graph_path, "rb") as compressed:
            payload = compressed.read()
        with tempfile.NamedTemporaryFile(suffix=".graphml", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        try:
            return ox.load_graphml(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    return ox.load_graphml(graph_path)


def load_graph() -> None:
    """Load saved roads once, or use estimate-only backup mode. Never download."""
    global _graph, _backup_mode
    if _graph is not None or _backup_mode:
        return

    graph_path = _resolve_graph_path()
    try:
        if not graph_path.is_file():
            raise FileNotFoundError(f"Saved road graph is missing or not a file: {graph_path}")
        graph = _load_graphml(graph_path)
        if len(graph) == 0 or graph.number_of_edges() == 0:
            raise ValueError("Saved graph contains no usable roads")
        graph.graph["routing_bbox"] = (
            min(float(n["x"]) for _, n in graph.nodes(data=True)),
            min(float(n["y"]) for _, n in graph.nodes(data=True)),
            max(float(n["x"]) for _, n in graph.nodes(data=True)),
            max(float(n["y"]) for _, n in graph.nodes(data=True)),
        )
    except Exception as error:
        # Only loading errors enable the backup, never routing failures.
        _backup_mode = True
        logging.getLogger(__name__).warning("%s File: %s. Error: %s", BACKUP_WARNING, graph_path, error)
        return
    _graph = graph
    _road_graph()  # also binds the traffic engine to this graph


# ---------- array road graph ----------

_rg_lock = threading.Lock()
_rg_cache = (None, None)   # (weak reference to the networkx graph, its RoadGraph)
_cell_tables: list = []    # [(RoadGraph, FireGrid, CellTable)], newest first


def _road_graph() -> RoadGraph:
    """The RoadGraph for the current `_graph`, built once (tests may swap `_graph`)."""
    global _rg_cache
    ref, rg = _rg_cache
    if ref is not None and ref() is _graph:
        return rg
    with _rg_lock:
        ref, rg = _rg_cache
        if ref is None or ref() is not _graph:
            rg = RoadGraph.from_networkx(_graph)
            _rg_cache = (weakref.ref(_graph), rg)
            traffic_engine.bind_graph(_graph, rg)
        return rg


def forget_road_graph() -> None:
    """Drop cached arrays, e.g. after a test edits `_graph` in place."""
    global _rg_cache
    with _rg_lock:
        _rg_cache = (None, None)
        _cell_tables.clear()


def _inside_demo(lat, lon):
    """Check coverage using the loaded road graph."""
    if _graph is not None:
        west, south, east, north = _graph.graph.get(
            "routing_bbox", DEMO_BBOX
        )
    else:
        west, south, east, north = DEMO_BBOX

    return west <= lon <= east and south <= lat <= north


def fire_closed_road_features(oracle, sim_time: int = 0, limit: int = 350) -> dict:
    """GeoJSON LineStrings for OSM edges past the fire/tornado close deadline.

    Contract rule: a road is closed once drivers would reach it after
    `arrival_min − 30`. Uses the same EdgeFire deadlines as /route.
    """
    empty = {
        "type": "FeatureCollection",
        "sim_time": int(sim_time),
        "count": 0,
        "features": [],
    }
    if oracle is None or validation_error(oracle) or _graph is None or len(_graph) == 0:
        return empty
    rg = _road_graph()
    try:
        edge_fire = EdgeFire.for_oracle(rg, _cell_table(rg, oracle), oracle)
    except ValueError:
        return empty
    t = float(sim_time)
    deadlines = edge_fire.edge_deadline
    closed = np.flatnonzero(np.isfinite(deadlines) & (deadlines < t))
    if len(closed) == 0:
        return empty
    overdue = t - deadlines[closed]
    # Prefer longer / named corridors so the red dash layer reads cleanly.
    lengths = np.maximum(rg.edge_len_m[closed].astype(np.float64), 1.0)
    named = np.ones(len(closed), dtype=np.float64)
    for i, e in enumerate(closed):
        label = rg.edge_name[int(e)] if int(e) < len(rg.edge_name) else ""
        if label and label != "Road":
            named[i] = 1.25
    score = overdue * np.log1p(lengths) * named
    order = closed[np.argsort(-score)][: max(1, int(limit))]
    features = []
    for e in order:
        coords = rg.edge_coords_ll(int(e)).tolist()
        if len(coords) < 2:
            continue
        name = rg.edge_name[int(e)] if int(e) < len(rg.edge_name) else "Road"
        features.append({
            "type": "Feature",
            "id": f"rd_closed_{int(e)}",
            "properties": {
                "kind": "closed_road",
                "name": name,
                "edge": int(e),
                "closed_at_sim_min": int(floor(float(deadlines[int(e)]))),
                "reason": "fire",
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    return {
        "type": "FeatureCollection",
        "sim_time": int(sim_time),
        "count": int(len(closed)),
        "features": features,
    }


# ---------- routes ----------

ROUTE_WARNING = ("Road routes with illustrative travel times at 30 km/h. Forecast checks cover every "
                 "fire-grid cell on the route; they are not a safety guarantee.")
_table_lock = threading.Lock()
_FLAT_FIELDS = ("shelter_id", "shelter_name", "distance_km", "eta_min", "geometry", "rerouted",
                "reroute_reason", "steps", "approximate", "warning", "forecast_complete")


def graph_bbox():
    """[min_lon, min_lat, max_lon, max_lat] of every road point, or None in backup mode."""
    if _graph is None:
        return None
    return list(_road_graph().bbox)


def _cell_table(rg: RoadGraph, oracle) -> CellTable:
    """Road-to-fire-cell table for this forecast's grid, built once per grid."""
    grid = FireGrid.of(oracle)
    for r, g, table in list(_cell_tables):
        if r is rg and g == grid:
            return table
    with _table_lock:
        for r, g, table in _cell_tables:
            if r is rg and g == grid:
                return table
        table = build_cell_table(rg, grid)
        _cell_tables.insert(0, (rg, grid, table))
        del _cell_tables[2:]
        return table


def prepare_forecast(oracle) -> None:
    """Build the cell table and this forecast's road deadlines ahead of the next /route.

    The API calls this on /sim/start and /sim/wind so phones don't pay for it.
    """
    if oracle is None or validation_error(oracle) or _graph is None or len(_graph) == 0:
        return
    rg = _road_graph()
    EdgeFire.for_oracle(rg, _cell_table(rg, oracle), oracle)


def find_routes(lat: float, lon: float, oracle, shelters: list[dict], sim_time: int = 0,
                check_route_id=None, debug: bool = False,
                hazards=None, forecast_outlines=None) -> dict:
    """2-4 road routes from the pin, each checked cell by cell against one forecast snapshot.

    `oracle` is the sim's frozen ForecastOracle, or None with no fire running.
    Known conflicts are `blocked`; a complete feasibility search is required
    before `no_safe_route` can be true. Unknown paths produce `indeterminate`;
    without a viable recommendation, `no_safe_route` is null. Raises NoRouteError only
    outside the demo area, with no road within 300 m, or with no open shelter
    reachable by road.
    """
    started = time.perf_counter()
    forecast_error = validation_error(oracle) if oracle is not None else None
    t_now = float(oracle.sim_time) if oracle is not None and not forecast_error else float(sim_time)
    if not isfinite(t_now) or t_now < 0:
        t_now = 0.0  # display fallback only; invalid forecasts remain indeterminate
    stats = Stats()
    if not _inside_demo(lat, lon):
        raise NoRouteError("No route in the Edmonton demo area")
    if _graph is None:
        if not _backup_mode:
            raise RuntimeError("Road graph is not loaded. Call load_graph() at startup.")
        rg = None
        candidates = straight_line_candidates(lat, lon, shelters, oracle, t_now,
                                              _inside_demo, stats)
    else:
        if len(_graph) == 0:
            raise NoRouteError("No route in the Edmonton demo area")
        rg = _road_graph()
        edge_fire = (EdgeFire.for_oracle(rg, _cell_table(rg, oracle), oracle)
                     if oracle is not None and not forecast_error else None)
        candidates = build_candidates(rg, edge_fire, oracle, lat, lon, shelters, t_now, stats,
                                      keep_id=check_route_id)
        rg = stats.routing_graph
    unsafe_ids = unsafe_shelter_ids(shelters, danger_rings(hazards, forecast_outlines))
    # Prefer a centre outside the dashboard yellow zone for the recommendation.
    check_id = check_route_id
    if check_id:
        kept = next((c for c in candidates if c.id == check_id), None)
        if kept is not None and kept.shelter["id"] in unsafe_ids:
            check_id = None
    safe_pool = [c for c in candidates if c.shelter["id"] not in unsafe_ids] or candidates
    chosen = select(rg, safe_pool, check_id, search_complete=stats.search_complete)
    options = mark_unsafe_shelters([_option(c, rg) for c in chosen.options], unsafe_ids)
    # Surface greyed unsafe alternatives that select() dropped when safer ones exist.
    shown = {o["id"] for o in options}
    for c in sorted(candidates, key=rank_key):
        if c.id in shown or c.shelter["id"] not in unsafe_ids:
            continue
        if len(options) >= 4:
            break
        options.append(mark_unsafe_shelters([_option(c, rg)], unsafe_ids)[0])
        shown.add(c.id)

    usable = [o for o in options if o["status"] in ("ok", "tight")]
    if not usable:
        for c in sorted(safe_pool, key=rank_key):
            if not viable(c.judgement):
                continue
            opt = _option(c, rg)
            if opt["status"] not in ("ok", "tight"):
                continue
            options = [opt] + [o for o in options if o["id"] != opt["id"]]
            usable = [opt]
            break

    best_id = usable[0]["id"] if usable else None
    # Leave-by: 30 min before the evacuation zone reaches you, or the route's own
    # road deadline if that comes first. Not reached within 4 h: no deadline at all.
    zone = zone_check(None if forecast_error else oracle, lat, lon, t_now)
    if zone.status == "reached":
        zone_leave_by = zone.reach_sim_min - BUFFER_MIN
        for o in options:
            if o["status"] in ("ok", "tight"):
                road = o["leave_by_sim_min"]
                o["leave_by_sim_min"] = zone_leave_by if road is None else min(road, zone_leave_by)
    elif zone.status == "clear":
        for o in options:
            o["leave_by_sim_min"] = None
    if best_id is not None:
        options = [o for o in options if o["id"] == best_id] + [o for o in options if o["id"] != best_id]
    # Same no_safe_route rule as select(): true only after a complete search with
    # no unresolved indeterminate candidates left in scope.
    unknown = (not stats.search_complete
               or any(o["status"] == "indeterminate" for o in options)
               or any(c.status == "indeterminate" for c in candidates))
    route_status = "viable" if best_id else ("indeterminate" if unknown else "blocked")
    no_safe = False if best_id else (None if unknown else True)

    body = {
        "lat": lat, "lon": lon, "sim_time": int(t_now),
        "best_route_id": best_id,
        "no_safe_route": no_safe,
        "route_status": route_status,
        "forecast_error": forecast_error,
        "search": {"complete": bool(stats.search_complete), "scope": stats.search_scope,
                   "shelters_evaluated": stats.shelters_evaluated},
        "leave_by_sim_min": None, "leave_by_label": None,
        "at_risk": {"reached": True, "clear": False}.get(zone.status),
        "zone_reach_sim_min": zone.reach_sim_min,
        "forecast": None if oracle is None or forecast_error else {
            "run_id": oracle.run_id, "band": oracle.band,
            "covers_until_sim_min": float(oracle.covers_until_sim_min),
            "wind_kmh": float(oracle.wind_kmh), "wind_from_deg": float(oracle.wind_from_deg),
        },
        "options": options[:4],
        "excluded": stats.excluded,
    }
    if best_id is not None:
        best = next(o for o in options if o["id"] == best_id)
        leave_by = best.get("leave_by_sim_min")
        if leave_by is not None:
            body["leave_by_sim_min"] = leave_by
            body["leave_by_label"] = f"Leave within {max(0, leave_by - int(t_now))} min (sim)"
        for name in _FLAT_FIELDS:
            body[name] = best[name]
    if debug:
        body["timings"] = {
            "snap_ms": round(stats.snap_ms, 2), "search_ms": round(stats.search_ms, 2),
            "safety_ms": round(stats.safety_ms, 2), "fixpoint_rounds": stats.fixpoint_rounds,
            "exact_fallbacks": stats.exact_fallbacks,
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    return body


def _option(c, rg) -> dict:
    j, path = c.judgement, c.path
    option = {
        "id": c.id,
        "role": c.role,
        "shelter_id": c.shelter["id"],
        "shelter_name": c.shelter["properties"].get("name", c.shelter["id"]),
        "distance_km": round(path.total_m / 1000.0, 1) if path.access_verified else None,
        "eta_min": int(ceil(path.total_min - 1e-9)) if path.access_verified else None,
        "arrival_sim_min": j.arrival_sim_min if path.access_verified else None,
        "modeled_distance_km": round(path.total_m / 1000., 3),
        "modeled_duration_min": path.total_min,
        "access": path.access or {"complete": False, "reason": "Road graph unavailable"},
        "geometry_scope": "complete_journey" if path.access_verified else "modeled_road_portions",
        "status": j.status,
        "margin_min": j.margin_min,
        "leave_by_sim_min": j.leave_by_sim_min,
        "clear_until_sim_min": j.clear_until_sim_min,
        "clear_until_label": (f"Clear until {t_label(j.clear_until_sim_min)}"
                              if j.clear_until_sim_min is not None else None),
        "reason": j.reason,
        "hazard_intercept": j.hazard_intercept,
        "shelter_threat_sim_min": j.shelter_threat_sim_min,
        "connector_m": int(round(path.connector_m)) if path.access_verified else None,
        "geometry": _geometry(path, rg),
        "steps": _steps(path, rg),
        "rerouted": c.role == "safest",
        "reroute_reason": "Route evaluated against mapped access and forecast constraints" if c.role == "safest" else None,
        "approximate": path.approximate,
        "warning": (BACKUP_WARNING + " Forecast checks are not a safety guarantee."
                    if path.approximate else ROUTE_WARNING),
        "forecast_complete": j.forecast_complete,
    }
    # Traffic fields (additive). JourneyGraph carries .parent.
    if hasattr(rg, "parent") and path.access_verified:
        traffic_engine.annotate_option(option, rg, path.edges)
        delay = option.get("traffic_delay_min") or 0
        if traffic_engine.enabled and delay >= 1 and c.role == "fastest":
            option["reroute_reason"] = option.get("reroute_reason") or f"Traffic adds {delay} min vs free-flow"
    else:
        option["traffic_delay_min"] = 0
        option["traffic_free_min"] = option.get("modeled_duration_min")
    return option


def _geometry(path, rg):
    """Only mapped portions; never draw a connecting chord across an unknown gap."""
    if not len(path.edges):
        return None
    from backend.routing.access import ON_ROAD_M
    lines, previous = [], None
    for e in path.edges:
        points = rg.edge_coords_ll(int(e)).tolist()
        xy = rg.edge_coords_xy(int(e))
        if previous is None or np.linalg.norm(previous - xy[0]) > ON_ROAD_M:
            lines.append(points)
        else:
            lines[-1].extend(points[1:])
        previous = xy[-1]
    if path.access["origin"]["status"] == "mapped":
        lines[0][0] = list(path.access["origin"]["point"])  # the pin, or its road point
    if path.access["destination"]["status"] == "mapped":
        lines[-1][-1] = list(path.shelter_ll)
    for i, points in enumerate(lines):
        dedup = [points[0]]
        for p in points[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        lines[i] = dedup if len(dedup) > 1 else dedup * 2
    return ({"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else
            {"type": "MultiLineString", "coordinates": lines})


def _steps(path, rg) -> list:
    steps = []
    for e in path.edges:
        name = rg.edge_name[int(e)]
        km = float(rg.edge_len_m[int(e)]) / 1000.0
        instruction = f"Continue on {name}"
        if steps and steps[-1]["instruction"] == instruction:
            steps[-1]["distance_km"] = round(steps[-1]["distance_km"] + km, 2)
        else:
            steps.append({"instruction": instruction, "distance_km": round(km, 2)})
    return steps
