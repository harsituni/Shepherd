"""Check the demo with four test nodes, never the saved Edmonton map."""

import unittest
from unittest.mock import patch

import networkx as nx

from backend.routing import router, wildfire_demo


class WildfireDemoTests(unittest.TestCase):
    def setUp(self):
        self.graph = nx.MultiDiGraph(crs="EPSG:4326")
        for node, lon, lat in [(1, -113.620, 53.520), (2, -113.570, 53.520),
                               (3, -113.516, 53.519), (4, -113.570, 53.540)]:
            self.graph.add_node(node, x=lon, y=lat)
        for start, end, length in [(1, 2, 3000), (2, 3, 3000), (1, 4, 4000), (4, 3, 4000)]:
            self.graph.add_edge(start, end, length=float(length))
        self.shelter = {
            "id": "sh_test", "properties": {"name": "Test shelter", "open": True, "capacity": 100, "occupancy": 0},
            "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
        }
        graph_patch = patch.object(router, "_graph", self.graph)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)
        for target in ["requests.sessions.Session.request", "osmnx.load_graphml", "osmnx.graph_from_bbox"]:
            blocked = patch(target, side_effect=AssertionError("Tests must use only the tiny graph"))
            blocked.start()
            self.addCleanup(blocked.stop)
        quiet = patch("builtins.print")
        self.printed = quiet.start()
        self.addCleanup(quiet.stop)

    def test_detour_avoids_fire(self):
        normal, detour = wildfire_demo.compare_routes(53.520, -113.620, self.shelter)
        self.assertEqual(normal["distance_km"], 6)
        self.assertEqual(detour["distance_km"], 8)
        self.assertTrue(detour["rerouted"])
        self.assertIn([-113.570, 53.540], detour["geometry"]["coordinates"])
        self.assertEqual(self.graph.number_of_edges(), 4)

    def test_no_alternative_is_reported(self):
        self.graph.remove_edge(1, 4)
        normal, detour = wildfire_demo.compare_routes(53.520, -113.620, self.shelter)
        self.assertEqual(normal["distance_km"], 6)
        self.assertIsNone(detour)
        self.printed.assert_any_call("New distance: unavailable. Rerouting: no reachable detour.", flush=True)

    def test_bad_detour_is_rejected(self):
        normal = router.find_route(53.520, -113.620, [], [self.shelter])
        bad_detour = dict(normal, rerouted=True)
        with patch.object(router, "find_route", side_effect=[normal, bad_detour]):
            with self.assertRaisesRegex(ValueError, "still touches"):
                wildfire_demo.compare_routes(53.520, -113.620, self.shelter)

    def test_missing_saved_graph_does_not_download(self):
        with patch("pathlib.Path.is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "Saved Edmonton graph missing"):
                wildfire_demo.main()


if __name__ == "__main__":
    unittest.main()
