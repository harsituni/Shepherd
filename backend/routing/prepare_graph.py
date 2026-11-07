"""Prepare demo roads only when --download is supplied."""

import argparse
import os
from pathlib import Path

import networkx as nx
import osmnx as ox

from backend.routing.router import DEMO_BBOX, ROUTING_DIR


GRAPH_PATH = ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
LOCATIONS = {
    "Kinsmen": (-113.516, 53.519),
    "Terwillegar": (-113.595, 53.440),
    "Commonwealth": (-113.473, 53.559),
    "Wildfire start": (-113.663, 53.535),
}
MAX_SNAP_METRES = 1000


def check_graph(graph):
    """Check nearby road nodes and directed routes without hazards."""
    print(f"Road graph: {len(graph)} nodes, {graph.number_of_edges()} edges")
    if len(graph) == 0:
        raise ValueError("The road graph is empty")

    longitudes = []
    latitudes = []
    for node, data in graph.nodes(data=True):
        longitudes.append(data["x"])
        latitudes.append(data["y"])
    west, east = min(longitudes), max(longitudes)
    south, north = min(latitudes), max(latitudes)

    nodes = {}
    covered = True
    for name, (lon, lat) in LOCATIONS.items():
        node, distance = ox.distance.nearest_nodes(graph, X=lon, Y=lat, return_dist=True)
        print(f"{name}: nearest road node is {distance:.0f} m away")
        if not (west <= lon <= east and south <= lat <= north):
            print(f"  Outside the saved graph's bounds: {name}")
            covered = False
        if distance > MAX_SNAP_METRES:
            print(f"  Too far from a road node: {name}")
            covered = False
        nodes[name] = node
    if not covered:
        raise ValueError("The graph does not cover all four demo locations")

    # Check both directions, including one-way roads.
    for start_name, start in nodes.items():
        for end_name, end in nodes.items():
            if start_name == end_name:
                continue
            try:
                distance = nx.shortest_path_length(graph, start, end, weight="length")
            except nx.NetworkXNoPath:
                raise ValueError(f"No road route from {start_name} to {end_name}") from None
            if distance <= 0:
                raise ValueError(f"No usable road route from {start_name} to {end_name}")
            print(f"{start_name} -> {end_name}: {distance / 1000:.2f} km")
    print("All four locations passed the baseline road checks (no hazards).")


def prepare_graph(path, download=False):
    """Reuse a saved file, or explicitly download the fixed demo area."""
    if path.exists():
        print(f"Checking saved roads: {path}")
        graph = ox.load_graphml(path)
        check_graph(graph)
        return
    if not download:
        raise FileNotFoundError(f"Saved graph missing: {path}. Use --download to prepare it.")

    overpass_url = os.environ.get("SHEPHERD_OVERPASS_URL")
    if overpass_url is not None:
        ox.settings.overpass_url = overpass_url

    # Let OSMnx split the area and reuse cached responses.
    ox.settings.cache_folder = str(ROUTING_DIR / "data" / "http_cache")
    ox.settings.use_cache = True
    ox.settings.max_query_area_size = 25_000_000
    ox.settings.overpass_rate_limit = True
    ox.settings.requests_timeout = 120
    ox.settings.log_console = True
    print(f"Downloading driving roads for {DEMO_BBOX}; press Ctrl+C to stop.")
    graph = ox.graph_from_bbox(DEMO_BBOX, network_type="drive", retain_all=True)

    # Save the roads for later.
    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, path)
    print(f"Saved roads: {path}")
    try:
        check_graph(graph)
    except ValueError as error:
        raise ValueError(
            f"Graph saved to {path}, but did not pass validation: {error}. "
            "The file was kept for offline inspection."
        ) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=GRAPH_PATH, help="GraphML file to check or save")
    parser.add_argument("--download", action="store_true", help="Allow downloads if the file is missing")
    args = parser.parse_args()
    try:
        prepare_graph(args.path, args.download)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
