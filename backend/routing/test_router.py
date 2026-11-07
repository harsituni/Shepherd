"""Offline tests for Step 1 road routing."""

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


# Small fake road map. Each point is (longitude, latitude).
POINTS = {
    1: (-113.50, 53.54),
    2: (-113.49, 53.54),
    3: (-113.48, 53.54),
    4: (-113.50, 53.55),
    5: (-113.501, 53.541),
}
BEND = (-113.495, 53.542)


def fake_graph():
    """Make a few roads without downloading anything."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for number, (lon, lat) in POINTS.items():
        graph.add_node(number, x=lon, y=lat)

    graph.add_edge(1, 2, length=900.0)
    graph.add_edge(1, 2, length=300.0,
                   geometry=LineString([POINTS[2], BEND, POINTS[1]]))
    graph.add_edge(2, 3, length=400.0)
    graph.add_edge(1, 3, length=2000.0)
    graph.add_edge(1, 4, length=1500.0)
    # Point 5 is not connected to the other roads.
    return graph


def shelter(name, node, is_open=True, capacity=100, occupancy=0):
    """Make a fake shelter at one of the road points."""
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
        # Give the router our small graph, not real Edmonton data.
        self.graph = fake_graph()
        graph_patch = patch.object(router, "_graph", self.graph)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

        # Fail the test if anything tries to download roads.
        download_patch = patch.object(
            router.ox, "graph_from_bbox",
            side_effect=AssertionError("A test tried to download roads"),
        ) 
        download_patch.start()
        self.addCleanup(download_patch.stop)

    def test_fire_uses_longer_road(self):
        # Find the shortest route without fire.
        shelters = [shelter("sh_a", 3)]
        normal = self.route(shelters)

        # Put a fire on the shorter curved road.
        fire = {
            "type": "Feature",
            "properties": {
                "kind": "wildfire",
                "zone": "core"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-113.496, 53.5415],
                    [-113.494, 53.5415],
                    [-113.494, 53.5425],
                    [-113.496, 53.5425],
                    [-113.496, 53.5415]
                ]]
            }
        }

        # Find another route around the fire.
        original_edges = self.graph.number_of_edges()
        detour = find_route(53.54, -113.50, [fire], shelters)

        # The new route should be longer.
        self.assertEqual(normal["distance_km"], 0.7)
        self.assertEqual(detour["distance_km"], 1.3)

        # Make sure the original roads were not changed.
        self.assertEqual(self.graph.number_of_edges(), original_edges)

    def route(self, shelters):
        return find_route(53.54, -113.50, [], shelters)

    def test_nearest_reachable_by_road_length(self):
        choices = [
            shelter("sh_disconnected", 5),
            shelter("sh_long_road", 4),
            shelter("sh_short_road", 3),
        ]
        result = self.route(choices)
        self.assertEqual(result["shelter_id"], "sh_short_road")
        self.assertEqual(result["distance_km"], 0.7)

    def test_curved_roads_and_shorter_parallel_road(self):
        result = self.route([shelter("sh_a", 3)])
        self.assertEqual(result["geometry"], {
            "type": "LineString",
            "coordinates": [
                list(POINTS[1]), list(BEND), list(POINTS[2]), list(POINTS[3])
            ],
        })
        self.assertEqual(result["distance_km"], 0.7)
        self.assertEqual(result["eta_min"], 2)

    def test_response_format(self):
        result = self.route([shelter("sh_a", 3)])
        self.assertEqual(set(result), {
            "shelter_id", "shelter_name", "distance_km", "eta_min",
            "rerouted", "reroute_reason", "steps", "geometry",
        })
        self.assertEqual(result["shelter_name"], "sh_a")
        self.assertIsInstance(result["distance_km"], float)
        self.assertIsInstance(result["eta_min"], int)
        self.assertFalse(result["rerouted"])
        self.assertIsNone(result["reroute_reason"])
        self.assertEqual(result["steps"], [])
        json.dumps(result, allow_nan=False)

    def test_closed_full_and_overfull_shelters(self):
        choices = [
            shelter("sh_closed", 2, is_open=False),
            shelter("sh_full", 2, occupancy=100),
            shelter("sh_overfull", 2, occupancy=101),
            shelter("sh_available", 3, occupancy=99),
        ]
        self.assertEqual(self.route(choices)["shelter_id"], "sh_available")

    def test_no_eligible_or_reachable_shelters(self):
        cases = [
            [],
            [shelter("sh_closed", 2, is_open=False)],
            [shelter("sh_full", 2, occupancy=100)],
            [shelter("sh_zero", 2, capacity=0)],
            [shelter("sh_unreachable", 5)],
        ]
        for choices in cases:
            with self.subTest(choices=choices):
                with self.assertRaises(NoRouteError):
                    self.route(choices)

    def test_one_way_roads(self):
        # Roads go from 1 to 3, but not backwards from 3 to 1.
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.48, [], [shelter("sh_start", 1)])

    def test_same_node_is_zero_distance(self):
        result = self.route([shelter("sh_here", 1)])
        self.assertEqual(result["distance_km"], 0.0)
        self.assertEqual(result["eta_min"], 0)
        self.assertEqual(result["geometry"]["coordinates"], [
            list(POINTS[1]), list(POINTS[1])
        ])

    def test_locations_snap_to_roads(self):
        destination = shelter("sh_a", 3)
        destination["geometry"]["coordinates"] = [-113.47999, 53.54001]
        result = find_route(53.54001, -113.50001, [], [destination])
        self.assertEqual(result["geometry"]["coordinates"][0], list(POINTS[1]))
        self.assertEqual(result["geometry"]["coordinates"][-1], list(POINTS[3]))

    def test_ties_keep_first_shelter(self):
        result = self.route([shelter("sh_a", 3), shelter("sh_b", 3)])
        self.assertEqual(result["shelter_id"], "sh_a")

    def test_no_route_when_fire_blocks_roads(self):
        hazards = [{
            "type": "Feature",
            "id": "hz_1",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-113.51, 53.53], [-113.47, 53.53], [-113.47, 53.56],
                [-113.51, 53.56], [-113.51, 53.53],
            ]]},
            }]
        shelters = [shelter("sh_a", 3)]
        original = deepcopy((hazards, shelters))
        # The fire blocks all roads, so there is no route.
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, hazards, shelters)

        self.assertEqual(closed_roads(hazards), [])
        self.assertEqual((hazards, shelters), original)

    def test_outside_demo_area(self):
        with self.assertRaises(NoRouteError):
            find_route(0, 0, [], [shelter("sh_a", 3)])
        outside = shelter("sh_outside", 3)
        outside["geometry"]["coordinates"] = [0, 0]
        with self.assertRaises(NoRouteError):
            self.route([outside])

    def test_graph_must_be_loaded(self):
        with patch.object(router, "_graph", None):
            with self.assertRaisesRegex(RuntimeError, "load_graph"):
                self.route([shelter("sh_a", 3)])
        with patch.object(router, "_graph", nx.MultiDiGraph()):
            with self.assertRaises(NoRouteError):
                self.route([shelter("sh_a", 3)])

    def test_function_names_stay_the_same(self):
        self.assertTrue(issubclass(NoRouteError, Exception))
        self.assertEqual(list(inspect.signature(load_graph).parameters), [])
        self.assertEqual(list(inspect.signature(find_route).parameters), [
            "lat", "lon", "hazards", "shelters",
        ])
        self.assertEqual(list(inspect.signature(closed_roads).parameters), ["hazards"])


class GraphLoadingTests(unittest.TestCase):
    def test_download_once_then_use_saved_file(self):
        # Pretend the download works, then check that the file is reused.
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router, "_graph", None), \
                 patch.object(router.ox.settings, "cache_folder"), \
                 patch.object(router.ox.settings, "use_cache"), \
                 patch.object(router.ox, "graph_from_bbox", return_value=fake_graph()) as download:
                load_graph()
                self.assertTrue(saved_file.exists())
                load_graph()
                download.assert_called_once_with(
                    router.DEMO_BBOX, network_type="drive", retain_all=True
                )
                # Clear the graph from memory; it should load from disk.
                router._graph = None
                load_graph()
                self.assertEqual(download.call_count, 1)
                result = find_route(53.54, -113.50, [], [shelter("sh_a", 3)])
                self.assertEqual(result["distance_km"], 0.7)
                self.assertIn(list(BEND), result["geometry"]["coordinates"])

    def test_download_error_does_not_make_up_a_route(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router, "_graph", None), \
                 patch.object(router.ox.settings, "cache_folder"), \
                 patch.object(router.ox.settings, "use_cache"), \
                 patch.object(router.ox, "graph_from_bbox", side_effect=ConnectionError("offline")):
                with self.assertRaisesRegex(ConnectionError, "offline"):
                    load_graph()
                self.assertIsNone(router._graph)


if __name__ == "__main__":
    unittest.main()
