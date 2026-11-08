"""SHEPHERD_ROUTING flag: v3 served when set, v2 untouched by default."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from backend.api import main as api
from backend.routing import router
from backend.sim.controller import SimController

PIN = (53.535, -113.64)
FIRE = api.SimStart(lat=53.535, lon=-113.663, wind_kmh=35, wind_from_deg=270)


class RouteFlagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roads = patch.multiple(router, _graph=None, _backup_mode=False)
        cls.roads.start()
        router.forget_road_graph()
        router.load_graph()
        if router._graph is None:
            cls.roads.stop()
            raise unittest.SkipTest("the saved Edmonton road graph is not available")

    @classmethod
    def tearDownClass(cls):
        cls.roads.stop()
        router.forget_road_graph()

    def setUp(self):
        self.controller = SimController(weather="dashboard")
        for name, value in (("controller", self.controller), ("ROUTING_VERSION", "v3")):
            p = patch.object(api, name, value)
            p.start()
            self.addCleanup(p.stop)

    def start_fire(self):
        self.controller.set_domain(api.graph_bbox())
        api.post_sim_start(FIRE)

    def test_v3_shape_is_served(self):
        self.start_fire()
        body = api.get_route(*PIN, check_route_id=None, debug=False)
        for key in ("best_route_id", "no_safe_route", "forecast", "options", "excluded", "search"):
            self.assertIn(key, body)
        self.assertTrue(body["search"]["complete"])
        self.assertEqual(body["search"]["scope"], "all_eligible_shelters_on_loaded_directed_graph")
        self.assertGreater(body["search"]["shelters_evaluated"], 0)
        self.assertTrue(all(o["id"].startswith("rt_") for o in body["options"]))
        self.assertEqual(body["forecast"]["band"], "p50")
        self.assertNotIn("timings", body)

    def test_debug_adds_timings(self):
        self.start_fire()
        body = api.get_route(*PIN, check_route_id=None, debug=True)
        self.assertEqual(set(body["timings"]),
                         {"snap_ms", "search_ms", "safety_ms", "fixpoint_rounds", "exact_fallbacks", "total_ms"})

    def test_out_of_area_is_404(self):
        response = api.get_route(53.0, -113.5, check_route_id=None, debug=False)
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"demo area", response.body)

    def test_all_blocked_is_still_200(self):
        self.start_fire()
        for _ in range(60):
            self.controller.tick()
        body = api.get_route(53.535, -113.663, check_route_id=None, debug=False)
        self.assertTrue(body["no_safe_route"])
        self.assertIsNone(body["best_route_id"])

    def test_start_and_wind_prepare_the_forecast(self):
        with patch.object(api, "prepare_forecast", wraps=api.prepare_forecast) as prepare:
            self.start_fire()
            api.post_sim_wind(api.SimWind(wind_kmh=20, wind_from_deg=90))
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(prepare.call_args.args[0].version, self.controller.oracle().version)

    def test_startup_sets_the_fire_domain_to_the_road_graph(self):
        async def startup():
            async with api.lifespan(api.app):
                return self.controller.domain_bbox

        self.assertEqual(asyncio.run(startup()), api.graph_bbox())

    def test_v2_stays_the_default_path(self):
        with patch.object(api, "ROUTING_VERSION", "v2"), \
                patch.object(api, "find_routes_v3") as v3, \
                patch.object(api, "prepare_forecast") as prepare:
            api.post_sim_start(FIRE)
            body = api.get_route(*PIN, check_route_id=None, debug=False)

            async def startup():
                async with api.lifespan(api.app):
                    return self.controller.domain_bbox

            self.assertIsNone(asyncio.run(startup()))
        v3.assert_not_called()
        prepare.assert_not_called()
        self.assertNotIn("no_safe_route", body)  # v2 shape
        self.assertNotIn("role", body["options"][0])


if __name__ == "__main__":
    unittest.main()
