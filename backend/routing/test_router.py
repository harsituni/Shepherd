"""Test real-road routing without downloading any roads."""

import inspect
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import networkx as nx
from shapely.geometry import LineString

import router
from router import NoRouteError, closed_roads, find_route, load_graph


# Fake road locations in Edmonton: (longitude, latitude)
POINTS = {
    1: (-113.50, 53.54),
    2: (-113.49, 53.54),
    3: (-113.48, 53.54),
    4: (-113.50, 53.55),
    5: (-113.501, 53.541),
}
BEND = (-113.495, 53.542)


def fake_graph():
    """Make a small road map for testing."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")

    for number, (lon, lat) in POINTS.items():
        graph.add_node(number, x=lon, y=lat)

    # Two roads go from 1 to 2. The curved one is shorter.
    graph.add_edge(1, 2, length=900.0)
    graph.add_edge(
        1, 2, length=300.0,
        geometry=LineString([POINTS[2], BEND, POINTS[1]]),
    )
    graph.add_edge(2, 3, length=400.0)
    graph.add_edge(1, 3, length=2000.0)
    graph.add_edge(1, 4, length=1500.0)

    # Point 5 has no roads leading to it.
    return graph


def shelter(name, node, is_open=True, capacity=100, occupancy=0):
    """Make a shelter at one of our fake road points."""
    return {
        "type": "Feature",
        "id": name,
        "properties": {
            "name": name,
            "open": is_open,
            "capacity": capacity,
            "occupancy": occupancy,
        },
        "geometry": {
            "type": "Point",
            "coordinates": list(POINTS[node]),
        },
    }


class RoutingTests(unittest.TestCase):
    def setUp(self):
        # Give each test the fake roads instead of downloading Edmonton.
        graph_patch = patch.object(router, "_graph", fake_graph())
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

        # Stop a test if it tries to use the internet.
        download_patch = patch.object(
            router.ox, "graph_from_bbox",
            side_effect=AssertionError("This test should not download roads"),
        )
        download_patch.start()
        self.addCleanup(download_patch.stop)

    def route(self, shelters):
        """Start a route from point 1."""
        return find_route(53.54, -113.50, [], shelters)

    def test_nearest_reachable_by_road_length(self):
        # Pick the shortest road route, not just the closest point.
        shelters = [
            shelter("sh_disconnected", 5),
            shelter("sh_long_road", 4),
            shelter("sh_short_road", 3),
        ]
        result = self.route(shelters)
        self.assertEqual(result["shelter_id"], "sh_short_road")
        self.assertEqual(result["distance_km"], 0.7)