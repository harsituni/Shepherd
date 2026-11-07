"""Check the smoke test on tiny roads without loading Edmonton."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from shapely.geometry import LineString

from backend.routing import fire_arrival_smoke, router
from backend.routing.test_router import POINTS, fake_graph, shelter


class FireArrivalSmokeTests(unittest.TestCase):
    def setUp(self):
        self.graph = fake_graph()
        self.graph[1][3][0]["geometry"] = LineString([
            POINTS[1], (-113.49, 53.56), POINTS[3],
        ])
        setting = patch.object(router, "_graph", self.graph)
        setting.start()
        self.addCleanup(setting.stop)

    def test_road_detour(self):
        with redirect_stdout(io.StringIO()) as output:
            normal, result = fire_arrival_smoke.compare_routes(53.54, -113.50, shelter("test", 3))
        self.assertIsNotNone(result)
        self.assertGreater(result["distance_km"], normal["distance_km"])
        self.assertIn("30-minute rule enforced: PASS", output.getvalue())
        self.assertIn("UNKNOWN", output.getvalue())

    def test_no_detour_is_reported(self):
        self.graph.remove_edge(1, 3)
        self.graph.remove_edge(1, 2, 0)
        with redirect_stdout(io.StringIO()) as output:
            normal, result = fire_arrival_smoke.compare_routes(53.54, -113.50, shelter("test", 3))
        self.assertIsNone(result)
        self.assertIn("Resulting distance: unavailable", output.getvalue())


if __name__ == "__main__":
    unittest.main()
