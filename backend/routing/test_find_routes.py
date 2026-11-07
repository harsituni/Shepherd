"""Tests for contract v2 find_routes / leave-by shaping."""

from __future__ import annotations

import unittest

from backend.routing.router import NoRouteError, find_routes


SHELTERS = [
    {
        "type": "Feature",
        "id": "sh_kinsmen",
        "properties": {"name": "Kinsmen Sports Centre", "open": True},
        "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
    },
    {
        "type": "Feature",
        "id": "sh_terwillegar",
        "properties": {"name": "Terwillegar Rec Centre", "open": True},
        "geometry": {"type": "Point", "coordinates": [-113.595, 53.440]},
    },
    {
        "type": "Feature",
        "id": "sh_commonwealth",
        "properties": {"name": "Commonwealth Rec Centre", "open": True},
        "geometry": {"type": "Point", "coordinates": [-113.473, 53.559]},
    },
]


class FindRoutesTests(unittest.TestCase):
    def test_no_fire_all_ok(self):
        body = find_routes(53.52, -113.62, lambda _lat, _lon: None, SHELTERS, sim_time=0)
        self.assertEqual(len(body["options"]), 3)
        self.assertTrue(all(o["status"] == "ok" for o in body["options"]))
        self.assertIn(body["best_route_id"], {o["id"] for o in body["options"]})
        self.assertIn("geometry", body)  # Step 0 compat
        self.assertIn("shelter_id", body)

    def test_fire_can_block_some(self):
        # Everything near west gets early fire; east later / never.
        def arrival(lat: float, lon: float):
            if lon < -113.55:
                return 40
            return None

        body = find_routes(53.52, -113.62, arrival, SHELTERS, sim_time=10)
        statuses = {o["status"] for o in body["options"]}
        self.assertTrue(statuses & {"ok", "tight", "blocked"})
        usable = [o for o in body["options"] if o["status"] in ("ok", "tight")]
        self.assertTrue(usable)
        self.assertIsNotNone(body["leave_by_sim_min"])
        self.assertTrue(body["leave_by_label"].startswith("Leave within"))

    def test_all_blocked_raises(self):
        def arrival(_lat: float, _lon: float):
            return 20  # fire everywhere soon

        with self.assertRaises(NoRouteError):
            find_routes(53.52, -113.62, arrival, SHELTERS, sim_time=0)


if __name__ == "__main__":
    unittest.main()
