"""Offline v2 tests using tiny roads, never the Edmonton graph."""

import unittest
from unittest.mock import patch

from backend.routing import router
from backend.routing.test_router import BEND, POINTS, fake_graph, shelter


class FindRoutesTests(unittest.TestCase):
    def setUp(self):
        self.graph = fake_graph()
        self.shelters = [shelter("sh_a", 2), shelter("sh_b", 3), shelter("sh_c", 4)]
        for name, value in (("_graph", self.graph), ("_backup_mode", False)):
            setting = patch.object(router, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        for name in ("load_graphml", "graph_from_bbox"):
            guard = patch.object(router.ox, name, side_effect=AssertionError("No map IO"))
            guard.start()
            self.addCleanup(guard.stop)

    def routes(self, arrival=None, sim_time=0):
        if arrival is None:
            arrival = lambda lat, lon: None
        return router.find_routes(53.54, -113.50, arrival, self.shelters, sim_time=sim_time)

    def test_no_fire_all_ok(self):
        body = self.routes()
        self.assertEqual(len(body["options"]), 3)
        self.assertTrue(all(option["status"] == "ok" for option in body["options"]))
        self.assertIsNone(body["leave_by_sim_min"])
        self.assertIsNone(body["options"][0]["margin_min"])
        self.assertEqual(
    body["options"][0]["clear_until_label"],
    "Fire timing unknown; no safety guarantee"
)
        self.assertFalse(body["options"][0]["forecast_complete"])
        self.assertIn("not a safety guarantee", body["warning"])
        self.assertEqual(body["shelter_id"], "sh_a")
        self.assertAlmostEqual(body["distance_km"], 0.3)
        self.assertIn(list(BEND), body["geometry"]["coordinates"])
        self.assertFalse(body["approximate"])

    def test_fire_can_block_some(self):
        body = self.routes(lambda lat, lon: 20 if lat > 53.545 else 120, sim_time=10)
        self.assertEqual({o["status"] for o in body["options"]}, {"ok", "blocked"})
        self.assertEqual(body["excluded"][0]["shelter_id"], "sh_c")
        self.assertEqual(body["leave_by_sim_min"], 89)
        self.assertEqual(body["leave_by_label"], "Leave within 79 min (sim)")

    def test_all_blocked_raises(self):
        with self.assertRaises(router.NoRouteError):
            self.routes(lambda lat, lon: 20)

    def test_fire_on_road_bend(self):
        def arrival(lat, lon):
            if abs(lat - BEND[1]) < 0.0001 and abs(lon - BEND[0]) < 0.0001:
                return 0
            return None
        body = self.routes(arrival)
        self.assertEqual(body["shelter_id"], "sh_a")
        self.assertEqual(len(body["excluded"]), 0)
        self.assertTrue(body["rerouted"])
        self.assertAlmostEqual(body["distance_km"], 0.9)
        self.assertNotIn(list(BEND), body["geometry"]["coordinates"])

    def test_fire_between_vertices(self):
        body = self.routes(lambda lat, lon: 0 if 53.544 < lat < 53.546 else None)
        self.assertEqual(body["excluded"][0]["shelter_id"], "sh_c")

    def test_buffer_boundary(self):
        self.shelters = [shelter("sh_a", 2)]
        body = self.routes(lambda lat, lon: 31)
        self.assertEqual(body["options"][0]["margin_min"], 0)
        self.assertEqual(body["options"][0]["status"], "tight")
        with self.assertRaises(router.NoRouteError):
            self.routes(lambda lat, lon: 31, sim_time=1)

    def test_shelter_eligibility(self):
        self.shelters = [shelter("closed", 2, is_open=False),
                         shelter("full", 3, occupancy=100), shelter("isolated", 5),
                         shelter("open", 4)]
        body = self.routes()
        self.assertEqual(len(body["options"]), 1)
        self.assertEqual(body["shelter_id"], "open")
        self.assertEqual(body["excluded"][0]["shelter_id"], "isolated")

    def test_no_path_does_not_enable_backup(self):
        self.shelters = [shelter("isolated", 5)]
        with self.assertRaises(router.NoRouteError):
            self.routes()
        self.assertFalse(router._backup_mode)

    def test_backup_is_labelled_and_checks_forecast(self):
        with patch.object(router, "_graph", None), patch.object(router, "_backup_mode", True):
            body = self.routes()
            self.assertTrue(body["approximate"])
            for option in body["options"]:
                self.assertTrue(option["approximate"])
                self.assertIn("not navigation instructions", option["warning"])
                self.assertEqual(len(option["geometry"]["coordinates"]), 2)
            with self.assertRaises(router.NoRouteError):
                self.routes(lambda lat, lon: 0)

    def test_check_route_updates_selected_timing(self):
        body = router.check_route(53.54, -113.50, "rt_sh_c", lambda lat, lon: 120,
                                  self.shelters, sim_time=10)
        self.assertEqual(body["best_route_id"], "rt_sh_c")
        self.assertEqual(body["shelter_id"], "sh_c")
        self.assertEqual(body["eta_min"], 3)
        self.assertEqual(body["leave_by_sim_min"], 87)
        self.assertEqual(body["leave_by_label"], "Leave within 77 min (sim)")

    def test_stable_ids(self):
        original = self.routes()
        self.shelters[0]["properties"]["open"] = False
        body = self.routes()
        old_ids = {o["shelter_id"]: o["id"] for o in original["options"]}
        for option in body["options"]:
            self.assertEqual(option["id"], old_ids[option["shelter_id"]])

    def test_check_route_replaces_blocked_choice(self):
        body = router.check_route(53.54, -113.50, "rt_sh_c",
                                  lambda lat, lon: 0 if lat > 53.545 else None,
                                  self.shelters)
        self.assertEqual(body["best_route_id"], "rt_sh_a")
        self.assertEqual(body["shelter_id"], "sh_a")

    def test_exact_buffer_is_allowed(self):
        self.shelters = [shelter("sh_a", 2)]
        for road in self.graph[1][2].values():
            road["length"] = 500.0
        body = self.routes(lambda lat, lon: 31)
        self.assertEqual(body["options"][0]["margin_min"], 0)
        with self.assertRaises(router.NoRouteError):
            self.routes(lambda lat, lon: 30.99)

    def test_cumulative_time_blocks_later_road(self):
        self.shelters = [shelter("sh_b", 3)]
        # Reaching node 2 takes one minute, then node 3 takes another.
        self.graph.remove_edge(1, 3)
        for road in self.graph[1][2].values():
            road["length"] = 500.0
        self.graph[2][3][0]["length"] = 500.0
        def arrival(lat, lon):
            return 31.5 if lon > -113.481 else None
        with self.assertRaises(router.NoRouteError):
            self.routes(arrival)
        self.graph[2][3][0]["length"] = 200.0
        body = self.routes(arrival)
        self.assertAlmostEqual(body["distance_km"], 0.7)
        self.assertFalse(body["forecast_complete"])
        self.assertIn("known samples only", body["warning"])

    def test_detour_through_different_nodes(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(4, 3, length=500.0)
        def arrival(lat, lon):
            return 0 if abs(lat - 53.54) < 0.0001 and -113.496 < lon < -113.484 else 120
        body = self.routes(arrival)
        self.assertTrue(body["rerouted"])
        self.assertEqual(body["geometry"]["coordinates"],
                         [list(POINTS[1]), list(POINTS[4]), list(POINTS[3])])
        self.assertAlmostEqual(body["distance_km"], 2.0)

    def test_reversed_detour_is_not_usable(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(3, 4, length=500.0)
        def arrival(lat, lon):
            return 0 if abs(lat - 53.54) < 0.0001 and -113.496 < lon < -113.484 else 120
        with self.assertRaises(router.NoRouteError):
            self.routes(arrival)

    def test_detour_can_also_be_too_late(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(4, 3, length=500.0)
        def arrival(lat, lon):
            if abs(lat - 53.54) < 0.0001 and -113.496 < lon < -113.484:
                return 0
            if lon > -113.481:
                return 33  # The detour takes four minutes.
            return 120
        with self.assertRaises(router.NoRouteError):
            self.routes(arrival)

    def test_advancing_clock_switches_to_detour(self):
        self.shelters = [shelter("sh_a", 2)]
        def arrival(lat, lon):
            return 31 if abs(lat - BEND[1]) < 0.0001 else None
        early = self.routes(arrival)
        later = self.routes(arrival, sim_time=1)
        self.assertAlmostEqual(early["distance_km"], 0.3)
        self.assertAlmostEqual(later["distance_km"], 0.9)
        self.assertTrue(later["rerouted"])

    def test_unknown_forecast_has_no_invented_deadline(self):
        body = self.routes()
        self.assertFalse(body["forecast_complete"])
        self.assertIsNone(body["leave_by_sim_min"])
        for option in body["options"]:
            self.assertIsNone(option["margin_min"])
            self.assertIsNone(option["clear_until_sim_min"])
            self.assertIn("unknown", option["warning"])

    def test_known_predictions_allow_early_driver(self):
        body = self.routes(lambda lat, lon: 120, sim_time=10)
        self.assertTrue(body["forecast_complete"])
        self.assertFalse(body["rerouted"])
        self.assertAlmostEqual(body["distance_km"], 0.3)
        self.assertEqual(body["options"][0]["margin_min"], 79)

    def test_check_route_keeps_shelter_with_a_detour(self):
        def arrival(lat, lon):
            return 0 if abs(lat - BEND[1]) < 0.0001 else None
        body = router.check_route(53.54, -113.50, "rt_sh_a", arrival, self.shelters)
        self.assertEqual(body["best_route_id"], "rt_sh_a")
        self.assertTrue(body["rerouted"])
        self.assertAlmostEqual(body["distance_km"], 0.9)

    def test_zero_length_route_still_checks_start(self):
        self.shelters = [shelter("start", 1)]
        self.assertEqual(self.routes()["distance_km"], 0)
        with self.assertRaises(router.NoRouteError):
            self.routes(lambda lat, lon: 0)

    def test_search_keeps_graph_unchanged(self):
        from copy import deepcopy
        import networkx as nx
        before = deepcopy(self.graph)
        self.routes(lambda lat, lon: 31 if abs(lat - BEND[1]) < 0.0001 else None,
                    sim_time=1)
        self.assertTrue(nx.utils.graphs_equal(before, self.graph))


if __name__ == "__main__":
    unittest.main()
