"""In-memory /evacuees upsert + 30s stale drop."""

from __future__ import annotations

import time
import unittest

from backend.api import main as api


class EvacueesTests(unittest.TestCase):
    def setUp(self) -> None:
        api.evacuees.clear()

    def tearDown(self) -> None:
        api.evacuees.clear()

    def test_upsert_two_ids(self):
        now = time.time()
        api.evacuees["ev_a"] = {
            "lat": 53.52,
            "lon": -113.61,
            "route_id": "rt_1",
            "route_status": "ok",
            "shelter_id": "sh_kinsmen",
            "updated_sim_time": 0,
            "last_seen": now,
        }
        api.evacuees["ev_b"] = {
            "lat": 53.53,
            "lon": -113.50,
            "route_id": "rt_2",
            "route_status": "tight",
            "shelter_id": "sh_commonwealth",
            "updated_sim_time": 0,
            "last_seen": now,
        }
        feats = api.evacuee_features()
        ids = {f["id"] for f in feats}
        self.assertEqual(ids, {"ev_a", "ev_b"})
        self.assertEqual(feats[0]["geometry"]["type"], "Point")

    def test_stale_dropped(self):
        api.evacuees["ev_old"] = {
            "lat": 53.52,
            "lon": -113.61,
            "route_id": None,
            "route_status": None,
            "shelter_id": None,
            "updated_sim_time": 0,
            "last_seen": 1_000_000.0,
        }
        api.evacuees["ev_new"] = {
            "lat": 53.53,
            "lon": -113.50,
            "route_id": None,
            "route_status": None,
            "shelter_id": None,
            "updated_sim_time": 0,
            "last_seen": 1_000_040.0,
        }
        api.prune_evacuees(now=1_000_040.0)
        self.assertNotIn("ev_old", api.evacuees)
        self.assertIn("ev_new", api.evacuees)


if __name__ == "__main__":
    unittest.main()
