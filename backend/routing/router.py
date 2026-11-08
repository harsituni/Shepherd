"""Road routing around core hazard polygons; routes are not safety-certified.

Routes and distances run between snapped road nodes, not building entrances.
eta_min is illustrative at 30 km/h, not an actual traffic estimate.
"""

from math import ceil, floor, isfinite
import gzip
import heapq
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import weakref

import numpy as np
import networkx as nx
import osmnx as ox

from shapely.geometry import LineString, Point, shape

from backend.routing.candidates import (
    NoRouteError, Stats, build_candidates, straight_line_candidates,
)
from backend.routing.road_graph import CellTable, FireGrid, RoadGraph, build_cell_table
from backend.routing.safety import EdgeFire, t_label
from backend.routing.select import select
from backend.sim.oracle import validation_error


ROUTING_DIR = Path(__file__).resolve().parent
GRAPH_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
GRAPH_GZ_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml.gz"
# West, south, east, north. Includes contract shelters; a bit larger than the
# downloaded graph so east/south pins still get backup routes instead of 404.
DEMO_BBOX = (-113.75, 53.40, -113.32, 53.62)
ILLUSTRATIVE_SPEED_KMH = 30.0
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
    rg = _road_graph()
    from backend.routing.traffic import engine as traffic_engine
    traffic_engine.bind_graph(graph, rg)


# ---------- array road graph (shared by v2 snapping and v3) ----------

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
            from backend.routing.traffic import engine as traffic_engine
            traffic_engine.bind_graph(_graph, rg)
        return rg


def forget_road_graph() -> None:
    """Drop cached arrays, e.g. after a test edits `_graph` in place."""
    global _rg_cache
    with _rg_lock:
        _rg_cache = (None, None)
        _cell_tables.clear()


def _nearest_osmid(lon, lat):
    rg = _road_graph()
    return rg.node_osmid[rg.nearest_node(lat, lon)[0]]


def _inside_demo(lat, lon):
    """Check coverage using the loaded road graph."""
    if _graph is not None:
        west, south, east, north = _graph.graph.get(
            "routing_bbox", DEMO_BBOX
        )
    else:
        west, south, east, north = DEMO_BBOX

    return west <= lon <= east and south <= lat <= north


def _straight_line_route(lat, lon, hazards, shelters):
    """Choose the nearest eligible shelter without crossing a core hazard."""
    if not _inside_demo(lat, lon):
        raise NoRouteError("No route in the Edmonton demo area")
    nearest = None
    best_distance = float("inf")
    best_coordinates = None
    for shelter in shelters:
        properties = shelter["properties"]
        if not properties["open"] or properties["occupancy"] >= properties["capacity"]:
            continue
        end_lon, end_lat = shelter["geometry"]["coordinates"]
        if not _inside_demo(end_lat, end_lon):
            continue
        coordinates = [[lon, lat], [end_lon, end_lat]]
        line = LineString(coordinates)
        blocked = False
        for hazard in hazards:
            if hazard["properties"].get("zone") != "core":
                continue
            area = shape(hazard["geometry"])
            if (line.intersects(area) or area.intersects(Point(lon, lat))
                    or area.intersects(Point(end_lon, end_lat))):
                blocked = True
                break
        if blocked:
            continue
        distance = float(ox.distance.great_circle(lat, lon, end_lat, end_lon)) / 1000
        if distance < best_distance:
            nearest = shelter
            best_distance = distance
            best_coordinates = coordinates
    if nearest is None:
        raise NoRouteError("No eligible shelter with a clear straight-line estimate")
    return {
        "shelter_id": nearest["id"],
        "shelter_name": nearest["properties"]["name"],
        "distance_km": round(best_distance, 1),
        "eta_min": ceil(best_distance / ILLUSTRATIVE_SPEED_KMH * 60),
        "rerouted": False,
        "reroute_reason": None,
        "steps": [],
        "geometry": {"type": "LineString", "coordinates": best_coordinates},
        "approximate": True,
        "warning": BACKUP_WARNING,
    }


def _shortest_edge(graph, start, end):
    """Choose the shortest road when two nodes have multiple connecting roads."""
    shortest = None
    for edge in graph[start][end].values():
        if shortest is None or edge["length"] < shortest["length"]:
            shortest = edge
    return shortest


def _edge_coordinates(graph, start, end, edge):
    """Follow this exact road in its driving direction."""
    start_point = [float(graph.nodes[start]["x"]), float(graph.nodes[start]["y"])]
    end_point = [float(graph.nodes[end]["x"]), float(graph.nodes[end]["y"])]

    # Follow the road's curves
    if edge.get("geometry") is not None:
        points = []
        for lon, lat in edge["geometry"].coords:
            points.append([float(lon), float(lat)])
        first_distance = (points[0][0] - start_point[0]) ** 2 + (points[0][1] - start_point[1]) ** 2
        last_distance = (points[-1][0] - start_point[0]) ** 2 + (points[-1][1] - start_point[1]) ** 2
        if last_distance < first_distance:
            points.reverse()
    else:
        points = [start_point, end_point]
    return points


def _route_details(graph, path):
    """Add road lengths and join road shapes in travel order."""
    distance_m = 0.0
    coordinates = []
    for index in range(len(path) - 1):
        start = path[index]
        end = path[index + 1]
        edge = _shortest_edge(graph, start, end)
        distance_m += edge["length"]
        points = _edge_coordinates(graph, start, end, edge)

        for point in points:
            if not coordinates or point != coordinates[-1]:
                coordinates.append(point)

    # Both locations can snap to the same node
    if len(path) == 1:
        node = graph.nodes[path[0]]
        point = [float(node["x"]), float(node["y"])]
        coordinates = [point, point.copy()]
    return distance_m / 1000.0, coordinates

def _blocked_edges(graph, hazards):
    """Find roads that cross a danger zone."""
    blocked = []

    for hazard in hazards:
        if hazard["properties"].get("zone") != "core":
            continue

        danger_area = shape(hazard["geometry"])

        for start, end, key, road in graph.edges(keys=True, data=True):
            # Use the road's shape if it exists.
            line = road.get("geometry")

            # Otherwise, draw a line between its two nodes.
            if line is None:
                a = graph.nodes[start]
                b = graph.nodes[end]
                line = LineString([
                    (a["x"], a["y"]),
                    (b["x"], b["y"])
                ])

            # Check if the road touches the danger area.
            if line.intersects(danger_area):
                blocked.append((start, end, key))

    return blocked

def _blocked_connection(lon, lat, node, hazards):
    """Check the location and its connection to the nearby road."""
    road_point = (_graph.nodes[node]["x"], _graph.nodes[node]["y"])
    connection = LineString([(lon, lat), road_point])
    for hazard in hazards:
        if hazard["properties"].get("zone") != "core":
            continue
        area = shape(hazard["geometry"])
        if area.intersects(Point(lon, lat)) or area.intersects(Point(road_point)):
            return True
        if connection.intersects(area):
            return True
    return False


def _path_roads(graph, path):
    """Remember which roads were used, including parallel roads."""
    roads = []
    for index in range(len(path) - 1):
        start, end = path[index], path[index + 1]
        shortest = _shortest_edge(graph, start, end)
        for key, road in graph[start][end].items():
            if road is shortest:
                roads.append((start, end, key))
                break
    return roads


def _road_name(edge) -> str:
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


def _steps_from_roads(graph, roads) -> list[dict]:
    """Collapse consecutive same-named edges into turn-by-turn style steps."""
    steps = []
    for start, end, key in roads:
        edge = graph[start][end][key]
        name = _road_name(edge)
        distance_km = float(edge["length"]) / 1000.0
        instruction = f"Continue on {name}"
        if steps and steps[-1]["instruction"] == instruction:
            steps[-1]["distance_km"] = round(steps[-1]["distance_km"] + distance_km, 2)
        else:
            steps.append({
                "instruction": instruction,
                "distance_km": round(distance_km, 2),
            })
    return steps


def _choose_route(graph, lat, lon, hazards, shelters):
    """Find the shortest reachable shelter on the given roads."""

    # Find nearby road nodes
    # Keep the same nearby nodes before and after closures.
    start = _nearest_osmid(lon, lat)
    if _blocked_connection(lon, lat, start, hazards):
        raise NoRouteError("The starting location or its road connection intersects a core hazard")
    nearest = None
    best_distance = float("inf")
    best_coordinates = None
    best_roads = None

    for shelter in shelters:
        properties = shelter["properties"]
        if not properties["open"]:
            continue
        if properties["occupancy"] >= properties["capacity"]:
            continue
        shelter_lon, shelter_lat = shelter["geometry"]["coordinates"]
        if not _inside_demo(shelter_lat, shelter_lon):
            continue
        end = _nearest_osmid(shelter_lon, shelter_lat)
        if _blocked_connection(shelter_lon, shelter_lat, end, hazards):
            continue

        # Find the shortest route
        try:
            path = nx.shortest_path(graph, start, end, weight="length")
        except nx.NetworkXNoPath:
            continue
        distance, coordinates = _route_details(graph, path)
        if distance < best_distance:
            nearest = shelter
            best_distance = distance
            best_coordinates = coordinates
            best_roads = _path_roads(graph, path)

    if nearest is None:
        raise NoRouteError("No reachable open shelter with available capacity")

    return nearest, best_distance, best_coordinates, best_roads


def find_route(lat: float, lon: float,
               hazards: list[dict],
               shelters: list[dict]) -> dict:
    """Compare roads with and without core hazards for this request.

    Inputs are Feature lists. ETA is illustrative, not a traffic estimate.
    The API layer must translate NoRouteError into the contract's HTTP 404.
    """
    if _graph is None:
        if _backup_mode:
            return _straight_line_route(lat, lon, hazards, shelters)
        raise RuntimeError("Road graph is not loaded. Call load_graph() at startup.")
    if len(_graph) == 0 or not _inside_demo(lat, lon):
        raise NoRouteError("No route in the Edmonton demo area")

    # No core polygons → one shortest-path search (skip the clone + second pass).
    if not hazards:
        nearest, best_distance, best_coordinates, roads = _choose_route(
            _graph, lat, lon, [], shelters
        )
        return {
            "shelter_id": nearest["id"],
            "shelter_name": nearest["properties"]["name"],
            "distance_km": round(best_distance, 1),
            "eta_min": ceil(best_distance / ILLUSTRATIVE_SPEED_KMH * 60),
            "rerouted": False,
            "reroute_reason": None,
            "steps": _steps_from_roads(_graph, roads),
            "geometry": {"type": "LineString", "coordinates": best_coordinates},
        }

    normal_shelter, _, _, normal_roads = _choose_route(_graph, lat, lon, [], shelters)

    # Remove blocked roads from a copy of the map.
    available_graph = _graph.copy()
    available_graph.remove_edges_from(_blocked_edges(_graph, hazards))
    nearest, best_distance, best_coordinates, roads = _choose_route(
        available_graph, lat, lon, hazards, shelters
    )

    rerouted = nearest["id"] != normal_shelter["id"] or roads != normal_roads
    reason = None
    if rerouted:
        reason = "Route changed because of a core hazard"

    return {
        "shelter_id": nearest["id"],
        "shelter_name": nearest["properties"]["name"],
        "distance_km": round(best_distance, 1),
        "eta_min": ceil(best_distance / ILLUSTRATIVE_SPEED_KMH * 60),
        "rerouted": rerouted,
        "reroute_reason": reason,
        "steps": _steps_from_roads(available_graph, roads),
        "geometry": {"type": "LineString", "coordinates": best_coordinates},
    }


def closed_roads(hazards: list[dict]) -> list[dict]:
    """Legacy stub — prefer `fire_closed_road_features` with the live oracle."""
    return []


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


def _line_samples(coordinates, minutes, elapsed=0.0):
    """Place timing samples along a road, including its bends."""
    lengths = []
    total = 0.0
    for index in range(len(coordinates) - 1):
        lon, lat = coordinates[index]
        end_lon, end_lat = coordinates[index + 1]
        length = float(ox.distance.great_circle(lat, lon, end_lat, end_lon))
        lengths.append(length)
        total += length

    samples = []
    travelled = 0.0
    for index, length in enumerate(lengths):
        lon, lat = coordinates[index]
        end_lon, end_lat = coordinates[index + 1]
        # Sample bends / long edges about every 120 m (was 50 m — too slow on
        # the full Edmonton graph when every Dijkstra edge is checked).
        count = max(1, ceil(length / 120))
        for step in range(count + 1):
            fraction = step / count
            offset = 0.0
            if total > 0:
                offset = (travelled + length * fraction) / total * minutes
            samples.append((
                lat + (end_lat - lat) * fraction,
                lon + (end_lon - lon) * fraction,
                elapsed + offset,
            ))
        travelled += length
    return samples


def _sample_timing(samples, arrival_min_fn, sim_time):
    """Compare driver arrival with the supplied fire prediction."""
    leave_by = None
    clear_until = None
    reason = None
    complete = True
    for lat, lon, offset in samples:
        fire_at = arrival_min_fn(lat, lon)
        if fire_at is None:
            complete = False
            continue
        deadline = fire_at - 30
        latest_start = floor(deadline - offset)
        if leave_by is None or latest_start < leave_by:
            leave_by = latest_start
        if clear_until is None or deadline < clear_until:
            clear_until = deadline
        if sim_time + offset > deadline and reason is None:
            reason = (
                f"Fire predicted near ({lat:.3f}, {lon:.3f}) at T+{fire_at}; "
                f"estimated arrival T+{sim_time + offset:.1f} misses the "
                f"30 minute buffer (T+{deadline})."
            )

    margin = None
    status = "ok"
    if leave_by is not None:
        margin = leave_by - sim_time
        if reason is not None:
            status = "blocked"
        elif margin < 60:
            status = "tight"
    return {
        "margin_min": margin,
        "status": status,
        "forecast_complete": complete,
        "clear_until_sim_min": clear_until if status != "blocked" else None,
        "clear_until_label": (
            f"Sampled forecast buffer until T+{clear_until} (estimate)"
            if clear_until is not None and status != "blocked" else None
        ),
        "reason": reason,
        "_leave_by": leave_by,
    }


def _route_timing(route, arrival_min_fn, sim_time):
    """Check a backup line using its unrounded travel time."""
    minutes = route["distance_km"] / ILLUSTRATIVE_SPEED_KMH * 60
    samples = _line_samples(route["geometry"]["coordinates"], minutes)
    return _sample_timing(samples, arrival_min_fn, sim_time)


def _forecast_route(lat, lon, shelter, arrival_min_fn, sim_time):
    """Find the shortest road path that meets all known fire deadlines."""
    end_lon, end_lat = shelter["geometry"]["coordinates"]
    start = _nearest_osmid(lon, lat)
    end = _nearest_osmid(end_lon, end_lat)
    node = _graph.nodes[start]
    start_samples = [(node["y"], node["x"], 0.0)]
    if _sample_timing(start_samples, arrival_min_fn, sim_time)["status"] == "blocked":
        raise NoRouteError("The starting road misses the 30 minute fire buffer")

    # Visit the earliest reachable road node first.
    distances = {start: 0.0}
    previous = {}
    pending = [(0.0, start)]
    while pending:
        distance, current = heapq.heappop(pending)
        if distance != distances[current]:
            continue
        if current == end:
            break
        elapsed = distance / 1000 / ILLUSTRATIVE_SPEED_KMH * 60
        for next_node, roads in _graph[current].items():
            for key, road in roads.items():
                next_distance = distance + road["length"]
                if next_distance >= distances.get(next_node, float("inf")):
                    continue
                coordinates = _edge_coordinates(_graph, current, next_node, road)
                minutes = road["length"] / 1000 / ILLUSTRATIVE_SPEED_KMH * 60
                samples = _line_samples(coordinates, minutes, elapsed)
                if _sample_timing(samples, arrival_min_fn, sim_time)["status"] == "blocked":
                    continue
                distances[next_node] = next_distance
                previous[next_node] = (current, key)
                heapq.heappush(pending, (next_distance, next_node))

    if end not in distances:
        raise NoRouteError("No road path meets the known 30 minute fire buffer")

    # Keep the exact parallel roads chosen by the search.
    roads = []
    current = end
    while current != start:
        before, key = previous[current]
        roads.append((before, current, key))
        current = before
    roads.reverse()
    coordinates = []
    samples = start_samples.copy()
    elapsed = 0.0
    for before, after, key in roads:
        road = _graph[before][after][key]
        points = _edge_coordinates(_graph, before, after, road)
        minutes = road["length"] / 1000 / ILLUSTRATIVE_SPEED_KMH * 60
        samples.extend(_line_samples(points, minutes, elapsed))
        elapsed += minutes
        for point in points:
            if not coordinates or point != coordinates[-1]:
                coordinates.append(point)
    if not roads:
        coordinates = [[float(node["x"]), float(node["y"])]] * 2
    return distances[end] / 1000, coordinates, _sample_timing(samples, arrival_min_fn, sim_time)



def _select_option(body, option):
    """Keep the selected option, timing and old response fields together."""
    body["best_route_id"] = option["id"]
    leave_by = option["leave_by_sim_min"]
    body["leave_by_sim_min"] = leave_by
    body["leave_by_label"] = None
    if leave_by is not None:
        body["leave_by_label"] = f"Leave within {max(0, leave_by - body['sim_time'])} min (sim)"
    for field in ("shelter_id", "shelter_name", "distance_km", "eta_min",
                  "geometry", "rerouted", "reroute_reason", "steps",
                  "approximate", "warning", "forecast_complete"):
        body[field] = option[field]


def _shelter_straight_km(lat, lon, shelter) -> float:
    end_lon, end_lat = shelter["geometry"]["coordinates"]
    return float(ox.distance.great_circle(lat, lon, end_lat, end_lon)) / 1000.0


def find_routes(lat: float, lon: float, arrival_min_fn,
                shelters: list[dict], sim_time: int = 0) -> dict:
    """Return up to three road options, checked against the supplied forecast.

    A missing forecast value is unknown, not a promised fire-free interval.
    The API currently supplies no core polygons to this v2 interface.
    """
    options = []
    excluded = []
    # Only the closest few shelters — we return at most 3 options anyway, and
    # fire-aware Dijkstra on every shelter was multi-second on the demo graph.
    eligible = []
    for shelter in shelters:
        properties = shelter["properties"]
        if not properties["open"] or properties["occupancy"] >= properties["capacity"]:
            continue
        eligible.append(shelter)
    eligible.sort(key=lambda shelter: _shelter_straight_km(lat, lon, shelter))
    candidates = eligible[:3]

    for shelter in candidates:
        try:
            option = find_route(lat, lon, [], [shelter])
        except NoRouteError as error:
            excluded.append({"shelter_id": shelter["id"], "reason": str(error)})
            continue
        # Shelter-based IDs stay stable when another option disappears.
        option["id"] = "rt_" + shelter["id"]
        # Fast path: time the normal shortest road. Only run the expensive
        # fire-avoiding search when that path is already forecast-blocked.
        timing = _route_timing(option, arrival_min_fn, sim_time)
        if (
            _graph is not None
            and timing.get("status") == "blocked"
        ):
            try:
                distance, coordinates, timing = _forecast_route(
                    lat, lon, shelter, arrival_min_fn, sim_time
                )
                changed = (
                    coordinates != option["geometry"]["coordinates"]
                    or round(distance, 1) != option["distance_km"]
                )
                option["geometry"]["coordinates"] = coordinates
                option["distance_km"] = round(distance, 1)
                option["eta_min"] = ceil(distance / ILLUSTRATIVE_SPEED_KMH * 60)
                option["rerouted"] = changed
                if changed:
                    option["reroute_reason"] = (
                        "Route changed because of predicted fire arrival"
                    )
            except NoRouteError as error:
                timing = {
                    "status": "blocked", "reason": str(error), "margin_min": None,
                    "clear_until_sim_min": None, "clear_until_label": None,
                    "_leave_by": None, "forecast_complete": False,
                }
        option.update(timing)
        option["leave_by_sim_min"] = option.pop("_leave_by")
        option["approximate"] = option.get("approximate", False)
        warning = option.get("warning", "Road geometry with illustrative travel times only.")
        warning += " Forecast checks sample the route; they are not a safety guarantee."
        # Incomplete forecast is a warning only — do not replace a missing
        # clear-until with an emergency-sounding label when no fire was sampled.
        if not option.get("forecast_complete", True) and option["status"] != "blocked":
            warning += (
                " Some fire arrival times are unknown; any margin or deadline "
                "covers known samples only."
            )
        option["warning"] = warning
        options.append(option)
        if option["status"] == "blocked":
            excluded.append({"shelter_id": shelter["id"], "reason": option["reason"]})

    usable = []
    for option in options:
        if option["status"] != "blocked":
            usable.append(option)
    if not usable:
        # Outside the demo box every shelter attempt fails the same way — don't
        # blame the fire forecast for a pin that was never routable.
        if not options and excluded:
            reasons = [entry["reason"] for entry in excluded]
            if reasons and all("demo area" in reason for reason in reasons):
                raise NoRouteError("No route in the Edmonton demo area")
        raise NoRouteError("No usable route under the supplied fire forecast")

    # No returned deadline is not a numeric safety margin.
    usable.sort(key=lambda option: (
        option["margin_min"] is None,
        option["margin_min"] if option["margin_min"] is not None else 0,
        -option["eta_min"],
    ), reverse=True)
    best = usable[0]
    options.sort(key=lambda option: (option["id"] != best["id"], option["distance_km"]))
    body = {
        "lat": lat, "lon": lon, "sim_time": sim_time,
        "options": options[:3], "excluded": excluded,
    }
    _select_option(body, best)
    return body


def check_route(lat: float, lon: float, route_id: str, arrival_min_fn,
                shelters: list[dict], sim_time: int = 0) -> dict:
    """Recalculate options and keep the chosen shelter if still usable."""
    body = find_routes(lat, lon, arrival_min_fn, shelters, sim_time=sim_time)
    for option in body["options"]:
        if option["id"] == route_id and option["status"] != "blocked":
            _select_option(body, option)
            break
    return body


# ---------- v3: 2-4 fire-checked road routes (the API default) ----------

V3_WARNING = ("Road routes with illustrative travel times at 30 km/h. Forecast checks cover every "
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


def find_routes_v3(lat: float, lon: float, oracle, shelters: list[dict], sim_time: int = 0,
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
    from backend.routing.evac_zone import danger_rings, mark_unsafe_shelters, unsafe_shelter_ids
    from backend.routing.safety import viable as _viable
    from backend.routing.select import rank_key as _rank_key

    unsafe_ids = unsafe_shelter_ids(shelters, danger_rings(hazards, forecast_outlines))
    # Prefer a centre outside the dashboard yellow zone for the recommendation.
    check_id = check_route_id
    if check_id:
        kept = next((c for c in candidates if c.id == check_id), None)
        if kept is not None and kept.shelter["id"] in unsafe_ids:
            check_id = None
    safe_pool = [c for c in candidates if c.shelter["id"] not in unsafe_ids] or candidates
    chosen = select(rg, safe_pool, check_id, search_complete=stats.search_complete)
    options = mark_unsafe_shelters([_v3_option(c, rg) for c in chosen.options], unsafe_ids)
    # Surface greyed unsafe alternatives that select() dropped when safer ones exist.
    shown = {o["id"] for o in options}
    for c in sorted(candidates, key=_rank_key):
        if c.id in shown or c.shelter["id"] not in unsafe_ids:
            continue
        if len(options) >= 4:
            break
        options.append(mark_unsafe_shelters([_v3_option(c, rg)], unsafe_ids)[0])
        shown.add(c.id)

    usable = [o for o in options if o["status"] in ("ok", "tight")]
    if not usable:
        for c in sorted(safe_pool, key=_rank_key):
            if not _viable(c.judgement):
                continue
            opt = _v3_option(c, rg)
            if opt["status"] not in ("ok", "tight"):
                continue
            options = [opt] + [o for o in options if o["id"] != opt["id"]]
            usable = [opt]
            break

    best_id = usable[0]["id"] if usable else None
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


def _v3_option(c, rg) -> dict:
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
        "geometry": _v3_geometry(path, rg),
        "steps": _v3_steps(path, rg),
        "rerouted": c.role == "safest",
        "reroute_reason": "Route evaluated against mapped access and forecast constraints" if c.role == "safest" else None,
        "approximate": path.approximate,
        "warning": (BACKUP_WARNING + " Forecast checks are not a safety guarantee."
                    if path.approximate else V3_WARNING),
        "forecast_complete": j.forecast_complete,
    }
    # Additive traffic fields (not in contract v2). JourneyGraph carries .parent.
    from backend.routing.traffic import engine as traffic_engine
    if hasattr(rg, "parent") and path.access_verified:
        traffic_engine.annotate_option(option, rg, path.edges)
        delay = option.get("traffic_delay_min") or 0
        if traffic_engine.enabled and delay >= 1 and c.role == "fastest":
            option["reroute_reason"] = option.get("reroute_reason") or f"Traffic adds {delay} min vs free-flow"
    else:
        option["traffic_delay_min"] = 0
        option["traffic_free_min"] = option.get("modeled_duration_min")
        option["_traffic_edge_ids"] = []
    return option


def _v3_geometry(path, rg):
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


def _v3_steps(path, rg) -> list:
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
