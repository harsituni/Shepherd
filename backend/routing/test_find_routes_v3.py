"""The 24 v2 find_routes tests, rewritten for routing v3 (same tiny roads, same intent).

What changed on purpose, per the v3 prompt:
- An unsafe route is kept and marked `blocked`; when every route is unsafe the
  answer still lists them with `no_safe_route: True` instead of raising.
- Fire is checked per 100 m grid cell, so arrival functions are evaluated at cell
  centres and point fires become one burning cell.
- Parallel roads collapse to the shortest one. Tests that relied on the 900 m
  parallel road as a detour add a separate detour road (4 -> 2) instead.
- `excluded` lists only shelters with no road route; option ids are
  rt_<shelter>_<role>; `forecast_complete` is true whenever a forecast covers the
  route (a cell the fire doesn't reach is "clear", not "unknown").
- The routes to sh_a and sh_b share sh_a's whole road, so the 80% overlap rule
  shows at most one of them.
"""

import unittest
from copy import deepcopy
from unittest.mock import patch

import networkx as nx

from backend.routing import router
from backend.routing.test_router import BEND, POINTS, fake_graph, shelter
from backend.routing.v3_testing import Forecast, grid_around

PIN = (53.54, -113.50)


class FindRoutesV3Tests(unittest.TestCase):
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
        router.forget_road_graph()
        self.addCleanup(router.forget_road_graph)
        self.grid = grid_around(list(POINTS.values()) + [BEND])

    def forecast(self, fn=None):
        fc = Forecast(self.grid)
        if fn is not None:
            fc.where(fn)
        return fc

    def routes(self, fc=None, sim_time=0, check=None):
        oracle = None if fc is None else fc.oracle(sim_time=sim_time)
        return router.find_routes_v3(*PIN, oracle, self.shelters, sim_time=sim_time, check_route_id=check)

    def option(self, body, route_id):
        return next(o for o in body["options"] if o["id"] == route_id)

    def assert_all_blocked(self, body):
        self.assertTrue(body["no_safe_route"])
        self.assertIsNone(body["best_route_id"])
        self.assertIsNone(body["leave_by_sim_min"])
        self.assertNotIn("shelter_id", body)  # no flat fields without a recommendation
        self.assertTrue(body["options"])
        self.assertTrue(all(o["status"] == "blocked" and o["reason"] for o in body["options"]))

    def test_no_fire_all_ok(self):
        body = self.routes()
        self.assertEqual([o["id"] for o in body["options"]], ["rt_sh_a_fastest", "rt_sh_c_fastest"])
        self.assertTrue(all(o["status"] == "ok" for o in body["options"]))
        self.assertIsNone(body["leave_by_sim_min"])
        self.assertIsNone(body["options"][0]["margin_min"])
        self.assertIsNone(body["options"][0]["clear_until_label"])
        self.assertTrue(body["options"][0]["forecast_complete"])
        self.assertIn("not a safety guarantee", body["warning"])
        self.assertEqual(body["shelter_id"], "sh_a")
        self.assertAlmostEqual(body["distance_km"], 0.3)
        self.assertIn(list(BEND), body["geometry"]["coordinates"])
        self.assertFalse(body["approximate"])
        self.assertFalse(body["no_safe_route"])

    def test_outside_demo_raises_demo_message(self):
        with self.assertRaises(router.NoRouteError) as raised:
            router.find_routes_v3(53.55, -113.20, None, self.shelters)
        self.assertIn("demo area", str(raised.exception))
        with patch.object(router, "_graph", None), patch.object(router, "_backup_mode", True):
            with self.assertRaises(router.NoRouteError) as raised:
                router.find_routes_v3(53.55, -113.20, None, self.shelters)
            self.assertIn("demo area", str(raised.exception))

    def test_fire_can_block_some(self):
        body = self.routes(self.forecast(lambda lat, lon: 20 if lat > 53.545 else 120), sim_time=10)
        self.assertEqual({o["status"] for o in body["options"]}, {"ok", "blocked"})
        blocked = self.option(body, "rt_sh_c_fastest")
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("Fire is expected", blocked["reason"])
        self.assertEqual(body["excluded"], [])
        self.assertEqual(body["best_route_id"], "rt_sh_a_fastest")
        self.assertEqual(body["leave_by_sim_min"], 89)
        self.assertEqual(body["leave_by_label"], "Leave within 79 min (sim)")

    def test_all_blocked_returns_greyed_options(self):
        body = self.routes(self.forecast(lambda lat, lon: 20))
        self.assert_all_blocked(body)
        self.assertTrue(2 <= len(body["options"]) <= 4)

    def test_fire_on_road_bend(self):
        fc = self.forecast()
        fc.at_point(BEND, 0)
        body = self.routes(fc)
        usual = self.option(body, "rt_sh_a_fastest")
        self.assertEqual(usual["status"], "blocked")
        self.assertIn("already", usual["reason"])
        self.assertIn(list(BEND), usual["geometry"]["coordinates"])
        # The distinct 900 m parallel road avoids the burning bend (F04).
        detour = self.option(body, "rt_sh_a_safest")
        self.assertEqual(detour["status"], "ok")
        self.assertEqual(detour["distance_km"], 0.9)
        self.assertNotIn(list(BEND), detour["geometry"]["coordinates"])
        self.assertEqual(body["best_route_id"], "rt_sh_a_safest")
        # B's safe path contains A's entire safe path, so display diversity may
        # retain A alone. Explicit selection still rebuilds and verifies B.
        selected_b = self.routes(fc, check="rt_sh_b_safest")
        detour = self.option(selected_b, "rt_sh_b_safest")
        self.assertEqual(detour["status"], "ok")
        self.assertTrue(detour["rerouted"])
        self.assertNotIn(list(BEND), detour["geometry"]["coordinates"])

    def test_fire_between_vertices(self):
        body = self.routes(self.forecast(lambda lat, lon: 0 if 53.544 < lat < 53.546 else None))
        blocked = self.option(body, "rt_sh_c_fastest")
        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(53.543 < blocked["hazard_intercept"]["lat"] < 53.547)
        self.assertNotIn(blocked["hazard_intercept"]["lat"], [p[1] for p in POINTS.values()])

    def test_buffer_boundary(self):
        self.shelters = [shelter("sh_a", 2)]
        everywhere_31 = self.forecast(lambda lat, lon: 31)
        body = self.routes(everywhere_31)
        self.assertEqual(body["options"][0]["margin_min"], 0)
        self.assertEqual(body["options"][0]["status"], "tight")
        self.assert_all_blocked(self.routes(everywhere_31, sim_time=1))

    def test_shelter_eligibility(self):
        self.shelters = [shelter("closed", 2, is_open=False),
                         shelter("full", 3, occupancy=100), shelter("isolated", 5),
                         shelter("open", 4)]
        body = self.routes()
        self.assertEqual([o["id"] for o in body["options"]], ["rt_open_fastest", "rt_isolated_fastest"])
        self.assertEqual(body["options"][1]["status"], "indeterminate")
        self.assertFalse(body["options"][1]["access"]["complete"])
        self.assertEqual(body["shelter_id"], "open")
        self.assertEqual({e["shelter_id"]: e["reason"] for e in body["excluded"]},
                         {"closed": "Shelter closed", "full": "Shelter full"})

    def test_no_path_does_not_enable_backup(self):
        self.shelters = [shelter("isolated", 5)]
        body = self.routes()
        self.assertIsNone(body["best_route_id"])
        self.assertIsNone(body["no_safe_route"])
        self.assertEqual(body["options"][0]["access"]["destination"]["status"], "unverified")
        self.assertFalse(router._backup_mode)

    def test_backup_is_labelled_and_checks_forecast(self):
        with patch.object(router, "_graph", None), patch.object(router, "_backup_mode", True):
            body = self.routes()
            self.assertIsNone(body["best_route_id"])
            self.assertIsNone(body["no_safe_route"])
            self.assertFalse(body["search"]["complete"])
            self.assertEqual(len(body["options"]), 3)
            for option in body["options"]:
                self.assertTrue(option["approximate"])
                self.assertIn("not navigation instructions", option["warning"])
                self.assertIsNone(option["geometry"])
                self.assertIsNone(option["eta_min"])
                self.assertEqual(option["status"], "indeterminate")
            burned = self.routes(self.forecast(lambda lat, lon: 0))
            self.assertTrue(all(o["status"] == "blocked" for o in burned["options"]))
            self.assertIsNone(burned["best_route_id"])
            self.assertIsNone(burned["no_safe_route"])  # no graph: no complete feasibility search

    def test_check_route_updates_selected_timing(self):
        body = self.routes(self.forecast(lambda lat, lon: 120), sim_time=10, check="rt_sh_c_fastest")
        self.assertEqual(body["best_route_id"], "rt_sh_c_fastest")
        self.assertEqual(body["options"][0]["id"], "rt_sh_c_fastest")
        self.assertEqual(body["shelter_id"], "sh_c")
        self.assertEqual(body["eta_min"], 3)
        self.assertEqual(body["leave_by_sim_min"], 87)
        self.assertEqual(body["leave_by_label"], "Leave within 77 min (sim)")

    def test_stable_ids(self):
        original = self.routes()
        self.shelters[0]["properties"]["open"] = False
        body = self.routes()
        for answer in (original, body):
            for option in answer["options"]:
                self.assertEqual(option["id"], f"rt_{option['shelter_id']}_{option['role']}")
        self.assertIn("rt_sh_c_fastest", {o["id"] for o in original["options"]})
        self.assertIn("rt_sh_c_fastest", {o["id"] for o in body["options"]})

    def test_check_route_keeps_blocked_choice_greyed(self):
        body = self.routes(self.forecast(lambda lat, lon: 0 if lat > 53.545 else None), check="rt_sh_c_fastest")
        self.assertEqual(body["best_route_id"], "rt_sh_a_fastest")
        self.assertEqual(body["shelter_id"], "sh_a")
        self.assertEqual(self.option(body, "rt_sh_c_fastest")["status"], "blocked")

    def test_exact_buffer_is_allowed(self):
        self.shelters = [shelter("sh_a", 2)]
        for road in self.graph[1][2].values():
            road["length"] = 500.0
        router.forget_road_graph()
        body = self.routes(self.forecast(lambda lat, lon: 31))
        self.assertEqual(body["options"][0]["margin_min"], 0)
        self.assertEqual(body["options"][0]["status"], "tight")
        self.assert_all_blocked(self.routes(self.forecast(lambda lat, lon: 30.99)))

    def test_cumulative_time_blocks_later_road(self):
        self.shelters = [shelter("sh_b", 3)]
        # Reaching node 2 takes one minute, then node 3 takes another.
        self.graph.remove_edge(1, 3)
        for road in self.graph[1][2].values():
            road["length"] = 500.0
        self.graph[2][3][0]["length"] = 500.0
        router.forget_road_graph()
        fc = self.forecast()
        fc.at_point(POINTS[3], 31.5)
        self.assert_all_blocked(self.routes(fc))
        self.graph[2][3][0]["length"] = 200.0
        router.forget_road_graph()
        body = self.routes(fc)
        self.assertAlmostEqual(body["distance_km"], 0.7)
        self.assertEqual(body["options"][0]["status"], "tight")
        self.assertTrue(body["forecast_complete"])

    def corridor(self, minute=0):
        """Fire on the straight east-west road between points 1 and 3, away from both ends."""
        fc = self.forecast()
        fc.along((-113.496, 53.54), (-113.484, 53.54), minute)
        return fc

    def test_detour_through_different_nodes(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(4, 3, length=500.0)
        body = self.routes(self.corridor())
        self.assertEqual(body["best_route_id"], "rt_sh_b_safest")
        self.assertTrue(body["rerouted"])
        self.assertEqual(body["geometry"]["coordinates"],
                         [list(POINTS[1]), list(POINTS[4]), list(POINTS[3])])
        self.assertAlmostEqual(body["distance_km"], 2.0)
        self.assertEqual(self.option(body, "rt_sh_b_fastest")["status"], "blocked")

    def test_reversed_detour_is_not_usable(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(3, 4, length=500.0)
        body = self.routes(self.corridor())
        self.assert_all_blocked(body)
        for option in body["options"]:
            coords = option["geometry"]["coordinates"]
            self.assertNotIn([list(POINTS[3]), list(POINTS[4])],
                             [coords[i:i + 2] for i in range(len(coords) - 1)])

    def test_detour_can_also_be_too_late(self):
        self.shelters = [shelter("sh_b", 3)]
        self.graph.add_edge(4, 3, length=500.0)
        fc = self.corridor()
        fc.at_point(POINTS[3], 33)  # The detour takes four minutes.
        self.assert_all_blocked(self.routes(fc))

    def test_advancing_clock_switches_to_detour(self):
        self.shelters = [shelter("sh_a", 2)]
        self.graph.remove_edge(1, 2, 0)  # isolate the via-4 detour; parallel roads have their own regression
        self.graph.add_edge(4, 2, length=600.0)  # a detour that misses the bend
        fc = self.forecast()
        fc.at_point(BEND, 31)
        early = self.routes(fc)
        later = self.routes(fc, sim_time=1)
        self.assertEqual(early["best_route_id"], "rt_sh_a_fastest")
        self.assertAlmostEqual(early["distance_km"], 0.3)
        self.assertEqual(later["best_route_id"], "rt_sh_a_safest")
        self.assertAlmostEqual(later["distance_km"], 2.1)
        self.assertTrue(later["rerouted"])
        self.assertEqual(self.option(later, "rt_sh_a_fastest")["status"], "blocked")

    def test_clear_forecast_has_expiry_deadline_but_no_invented_fire(self):
        for fc in (None, self.forecast()):  # no fire, and a fire that reaches none of these roads
            body = self.routes(fc)
            self.assertTrue(body["forecast_complete"])
            if fc is None:
                self.assertIsNone(body["leave_by_sim_min"])
            else:
                self.assertEqual(body["leave_by_sim_min"], 99909)
            for option in body["options"]:
                self.assertEqual(option["status"], "ok")
                if fc is None:
                    self.assertIsNone(option["margin_min"])
                    self.assertIsNone(option["leave_by_sim_min"])
                else:
                    # H=100000, reserve=90, trips are 0.6 and 3 minutes.
                    deadline = {"rt_sh_a_fastest": 99909, "rt_sh_c_fastest": 99907}[option["id"]]
                    self.assertEqual(option["leave_by_sim_min"], deadline)
                    self.assertEqual(option["margin_min"], deadline)
                self.assertIsNone(option["clear_until_sim_min"])
                self.assertIsNone(option["hazard_intercept"])

    def test_known_predictions_allow_early_driver(self):
        body = self.routes(self.forecast(lambda lat, lon: 120), sim_time=10)
        self.assertTrue(body["forecast_complete"])
        self.assertFalse(body["rerouted"])
        self.assertAlmostEqual(body["distance_km"], 0.3)
        self.assertEqual(body["options"][0]["margin_min"], 79)

    def test_check_route_keeps_shelter_with_a_detour(self):
        self.graph.remove_edge(1, 2, 0)  # exercise the via-4 path rather than the newly retained parallel
        self.graph.add_edge(4, 2, length=600.0)
        fc = self.forecast()
        fc.at_point(BEND, 0)
        body = self.routes(fc, check="rt_sh_a_safest")
        self.assertEqual(body["best_route_id"], "rt_sh_a_safest")
        self.assertTrue(body["rerouted"])
        self.assertAlmostEqual(body["distance_km"], 2.1)
        # A picked usual road that the fire cuts stays listed, greyed; the best moves on.
        body = self.routes(fc, check="rt_sh_a_fastest")
        self.assertEqual(self.option(body, "rt_sh_a_fastest")["status"], "blocked")
        self.assertNotEqual(body["best_route_id"], "rt_sh_a_fastest")

    def test_zero_length_route_still_checks_start(self):
        self.shelters = [shelter("start", 1)]
        body = self.routes()
        self.assertEqual(body["distance_km"], 0)
        self.assertEqual(body["geometry"]["coordinates"], [list(POINTS[1]), list(POINTS[1])])
        self.assert_all_blocked(self.routes(self.forecast(lambda lat, lon: 0)))

    def test_search_keeps_graph_unchanged(self):
        before = deepcopy(self.graph)
        fc = self.forecast()
        fc.at_point(BEND, 31)
        self.routes(fc, sim_time=1)
        self.assertTrue(nx.utils.graphs_equal(before, self.graph))


if __name__ == "__main__":
    unittest.main()
