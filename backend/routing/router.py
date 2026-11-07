"""Step 1 road routing. Hazards are ignored; routes are not safety-checked.

Routes and distances run between snapped road nodes, not building entrances.
eta_min is illustrative at 30 km/h, not an actual traffic estimate.
"""

from math import ceil
from pathlib import Path

import networkx as nx
import osmnx as ox


ROUTING_DIR = Path(__file__).resolve().parent
GRAPH_PATH = ROUTING_DIR / "data" / "edmonton_drive.graphml"
# West, south, east, north; includes the contract's example shelters.
DEMO_BBOX = (-113.70, 53.42, -113.43, 53.58)
ILLUSTRATIVE_SPEED_KMH = 30.0
_graph = None


class NoRouteError(Exception):
    """Used when no eligible shelter can be reached on the demo roads."""


def load_graph() -> None:
    """Load saved roads, or download and save them on the first run.

    Call once at startup. Download and file errors propagate to the caller.
    """
    global _graph
    if _graph is not None:
        return

    # Load the roads
    if GRAPH_PATH.exists():
        graph = ox.load_graphml(GRAPH_PATH)
    else:
        GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
        ox.settings.cache_folder = str(ROUTING_DIR / "data" / "http_cache")
        ox.settings.use_cache = True
        graph = ox.graph_from_bbox(DEMO_BBOX, network_type="drive", retain_all=True)
        ox.save_graphml(graph, GRAPH_PATH)
    _graph = graph


def _inside_demo(lat, lon):
    """Check that a location is inside the downloaded demo area."""
    west, south, east, north = DEMO_BBOX
    return west <= lon <= east and south <= lat <= north


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


def find_route(lat: float, lon: float,
               hazards: list[dict],
               shelters: list[dict]) -> dict:
    """Choose the shortest reachable road route. Hazards are ignored for now.

    Inputs are Feature lists. ETA is illustrative, not a traffic estimate.
    The API layer must translate NoRouteError into the contract's HTTP 404.
    """
    if _graph is None:
        raise RuntimeError("Road graph is not loaded. Call load_graph() at startup.")
    if len(_graph) == 0 or not _inside_demo(lat, lon):
        raise NoRouteError("No route in the Edmonton demo area")

    # Find nearby road nodes
    start = ox.distance.nearest_nodes(_graph, X=lon, Y=lat)
    nearest = None
    best_distance = float("inf")
    best_coordinates = None

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

        # Find the shortest route
        try:
            path = nx.shortest_path(_graph, start, end, weight="length")
        except nx.NetworkXNoPath:
            continue
        distance, coordinates = _route_details(_graph, path)
        if distance < best_distance:
            nearest = shelter
            best_distance = distance
            best_coordinates = coordinates

    if nearest is None:
        raise NoRouteError("No reachable open shelter with available capacity")

    return {
        "shelter_id": nearest["id"],
        "shelter_name": nearest["properties"]["name"],
        "distance_km": best_distance,
        "eta_min": ceil(best_distance / ILLUSTRATIVE_SPEED_KMH * 60),
        "rerouted": False,
        "reroute_reason": None,
        "steps": [],
        "geometry": {"type": "LineString", "coordinates": best_coordinates},
    }


def closed_roads(hazards: list[dict]) -> list[dict]:
    """Placeholder for Step 2; an empty list does not mean roads are safe."""
    return []
