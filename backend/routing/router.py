"""Road routing around core hazard polygons; routes are not safety-certified.

Routes and distances run between snapped road nodes, not building entrances.
eta_min is illustrative at 30 km/h, not an actual traffic estimate.
"""

from math import ceil, floor
import logging
import os
from pathlib import Path

import networkx as nx
import osmnx as ox

from shapely.geometry import LineString, Point, shape


ROUTING_DIR = Path(__file__).resolve().parent
GRAPH_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
# West, south, east, north; includes the contract's example shelters.
DEMO_BBOX = (-113.70, 53.42, -113.43, 53.58)
ILLUSTRATIVE_SPEED_KMH = 30.0
_graph = None
_backup_mode = False
BACKUP_WARNING = (
    "Road graph unavailable. Straight-line distance and ETA are estimates only, "
    "not navigation instructions or a verified safe driving route."
)


class NoRouteError(Exception):
    """Used when no eligible shelter can be reached on the demo roads."""


def load_graph() -> None:
    """Load saved roads once, or use estimate-only backup mode. Never download."""
    global _graph, _backup_mode
    if _graph is not None or _backup_mode:
        return

    saved_path = os.environ.get("SHEPHERD_GRAPH_PATH")
    graph_path = GRAPH_PATH
    try:
        if saved_path is not None:
            graph_path = Path(saved_path)
        if not graph_path.is_file():
            raise FileNotFoundError(f"Saved road graph is missing or not a file: {graph_path}")
        graph = ox.load_graphml(graph_path)
        if len(graph) == 0 or graph.number_of_edges() == 0:
            raise ValueError("Saved graph contains no usable roads")
    except Exception as error:
        # Only loading errors enable the backup, never routing failures.
        _backup_mode = True
        logging.getLogger(__name__).warning("%s File: %s. Error: %s", BACKUP_WARNING, graph_path, error)
        return
    _graph = graph


def _inside_demo(lat, lon):
    """Check that a location is inside the downloaded demo area."""
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
        "distance_km": best_distance,
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


def _route_details(graph, path):
    """Add road lengths and join road shapes in travel order."""
    distance_m = 0.0
    coordinates = []
    for index in range(len(path) - 1):
        start = path[index]
        end = path[index + 1]
        edge = _shortest_edge(graph, start, end)
        distance_m += edge["length"]
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


def _choose_route(graph, lat, lon, hazards, shelters):
    """Find the shortest reachable shelter on the given roads."""

    # Find nearby road nodes
    # Keep the same nearby nodes before and after closures.
    start = ox.distance.nearest_nodes(_graph, X=lon, Y=lat)
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
        end = ox.distance.nearest_nodes(_graph, X=shelter_lon, Y=shelter_lat)
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
        "distance_km": best_distance,
        "eta_min": ceil(best_distance / ILLUSTRATIVE_SPEED_KMH * 60),
        "rerouted": rerouted,
        "reroute_reason": reason,
        "steps": [],
        "geometry": {"type": "LineString", "coordinates": best_coordinates},
    }


def closed_roads(hazards: list[dict]) -> list[dict]:
    """Placeholder for Step 2; an empty list does not mean roads are safe."""
    return []


def _route_timing(route, arrival_min_fn, sim_time):
    """Sample the route geometry using the simulation's arrival times."""
    coordinates = route["geometry"]["coordinates"]
    lengths = []
    total = 0.0
    for index in range(len(coordinates) - 1):
        lon, lat = coordinates[index]
        end_lon, end_lat = coordinates[index + 1]
        length = float(ox.distance.great_circle(lat, lon, end_lat, end_lon))
        lengths.append(length)
        total += length

    leave_by = None
    clear_until = None
    reason = None
    travelled = 0.0
    for index, length in enumerate(lengths):
        lon, lat = coordinates[index]
        end_lon, end_lat = coordinates[index + 1]
        # Check bends and points at most 50 metres apart.
        count = max(1, ceil(length / 50))
        for step in range(count + 1):
            fraction = step / count
            sample_lat = lat + (end_lat - lat) * fraction
            sample_lon = lon + (end_lon - lon) * fraction
            fire_at = arrival_min_fn(sample_lat, sample_lon)
            if fire_at is None:
                continue
            offset = 0.0
            if total > 0:
                offset = (travelled + length * fraction) / total * route["eta_min"]
            deadline = fire_at - 30
            latest_start = floor(deadline - offset)
            if leave_by is None or latest_start < leave_by:
                leave_by = latest_start
            if clear_until is None or deadline < clear_until:
                clear_until = deadline
            if sim_time + offset > deadline and reason is None:
                reason = (
                    f"Fire predicted near ({sample_lat:.3f}, {sample_lon:.3f}) "
                    f"at T+{fire_at}; estimated arrival T+{sim_time + offset:.1f} "
                    f"misses the 30 minute buffer (T+{deadline})."
                )
        travelled += length

    margin = None
    status = "ok"
    if leave_by is not None:
        margin = leave_by - sim_time
        if margin < 0:
            status = "blocked"
        elif margin < 60:
            status = "tight"
    return {
        "margin_min": margin,
        "status": status,
        "clear_until_sim_min": clear_until if status != "blocked" else None,
        "clear_until_label": (
            f"Sampled forecast buffer until T+{clear_until} (estimate)"
            if clear_until is not None and status != "blocked" else None
        ),
        "reason": reason,
        "_leave_by": leave_by,
    }


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
                  "approximate", "warning"):
        body[field] = option[field]


def find_routes(lat: float, lon: float, arrival_min_fn,
                shelters: list[dict], sim_time: int = 0) -> dict:
    """Return up to three road options, checked against the supplied forecast.

    A missing forecast value is unknown, not a promised fire-free interval.
    The API currently supplies no core polygons to this v2 interface.
    """
    options = []
    excluded = []
    for shelter in shelters:
        properties = shelter["properties"]
        if not properties["open"] or properties["occupancy"] >= properties["capacity"]:
            continue
        try:
            option = find_route(lat, lon, [], [shelter])
        except NoRouteError as error:
            excluded.append({"shelter_id": shelter["id"], "reason": str(error)})
            continue
        # Shelter-based IDs stay stable when another option disappears.
        option["id"] = "rt_" + shelter["id"]
        option.update(_route_timing(option, arrival_min_fn, sim_time))
        option["leave_by_sim_min"] = option.pop("_leave_by")
        option["approximate"] = option.get("approximate", False)
        warning = option.get("warning", "Road geometry with illustrative travel times only.")
        warning += " Forecast checks sample the route; they are not a safety guarantee."
        if option["margin_min"] is None:
            warning += " No fire arrival returned at sampled points; margin and deadline are unknown."
            option["clear_until_label"] = "Fire timing unknown; no safety guarantee"
        option["warning"] = warning
        options.append(option)
        if option["status"] == "blocked":
            excluded.append({"shelter_id": shelter["id"], "reason": option["reason"]})

    usable = []
    for option in options:
        if option["status"] != "blocked":
            usable.append(option)
    if not usable:
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
