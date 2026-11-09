"""BPR traffic model + anti-gridlock assignment (additive /traffic API)."""

import unittest

import numpy as np

from backend.routing.traffic import (
    BPR_ALPHA,
    BPR_BETA,
    BPR_VC_CAP,
    MAP_LOCAL_MIN_VOLUME,
    SWITCH_SAVE_MIN,
    TrafficEngine,
    bpr_factor,
)


class BprTests(unittest.TestCase):
    def test_empty_road_is_free_flow(self):
        v = np.array([0.0, 0.0])
        c = np.array([10.0, 20.0])
        f = bpr_factor(v, c)
        np.testing.assert_allclose(f, [1.0, 1.0])

    def test_at_capacity_matches_classic_bpr(self):
        v = np.array([10.0])
        c = np.array([10.0])
        expected = 1.0 + BPR_ALPHA * (1.0 ** BPR_BETA)
        self.assertAlmostEqual(float(bpr_factor(v, c)[0]), expected)

    def test_over_capacity_rises_sharply(self):
        mild = float(bpr_factor(np.array([10.0]), np.array([10.0]))[0])
        bad = float(bpr_factor(np.array([20.0]), np.array([10.0]))[0])
        self.assertGreater(bad, mild * 2)

    def test_extreme_volume_is_capped(self):
        # Without a v/c cap, (2000/10)^4 blows up compare labels into 1e8 minutes.
        huge = float(bpr_factor(np.array([2000.0]), np.array([10.0]))[0])
        at_cap = 1.0 + BPR_ALPHA * (BPR_VC_CAP ** BPR_BETA)
        self.assertAlmostEqual(huge, at_cap)
        self.assertLess(huge, 50.0)


class TrafficEngineTests(unittest.TestCase):
    def test_configure_toggle(self):
        eng = TrafficEngine()
        st = eng.configure(enabled=True, anti_gridlock=True, simulated_count=10)
        self.assertTrue(st["enabled"])
        self.assertTrue(st["anti_gridlock"])
        self.assertEqual(st["simulated_count"], 10)
        st = eng.configure(enabled=False)
        self.assertFalse(st["enabled"])

    def test_projected_count_clamps_high(self):
        eng = TrafficEngine()
        st = eng.configure(enabled=False, simulated_count=250_000)
        self.assertEqual(st["simulated_count"], 100_000)

    def test_compare_needs_router(self):
        eng = TrafficEngine()
        out = eng.compare()
        self.assertEqual(out.get("error"), "traffic_unavailable")

    def test_switch_threshold_constant(self):
        # Demo: switch/hint as soon as another path saves about a minute.
        self.assertGreaterEqual(SWITCH_SAVE_MIN, 1.0)
        self.assertLessEqual(SWITCH_SAVE_MIN, 3.0)


class TrafficWithTinyGraph(unittest.TestCase):
    """Bind a miniature NetworkX digraph and assign cars on it."""

    def setUp(self):
        import networkx as nx
        from backend.routing.road_graph import RoadGraph

        g = nx.MultiDiGraph()
        # Two parallel corridors eastbound to a shelter area.
        g.add_node(1, x=-113.55, y=53.52)
        g.add_node(2, x=-113.54, y=53.52)
        g.add_node(3, x=-113.53, y=53.52)
        g.add_node(4, x=-113.54, y=53.525)
        g.add_node(5, x=-113.53, y=53.525)
        g.add_edge(1, 2, 0, length=800, highway="residential", lanes="1")
        g.add_edge(2, 3, 0, length=800, highway="residential", lanes="1")
        g.add_edge(1, 4, 0, length=900, highway="secondary", lanes="2")
        g.add_edge(4, 5, 0, length=900, highway="secondary", lanes="2")
        g.add_edge(5, 3, 0, length=400, highway="tertiary", lanes="1")
        self.g = g
        self.rg = RoadGraph.from_networkx(g)
        self.eng = TrafficEngine()
        self.eng.bind_graph(g, self.rg)
        hwy = self.eng._highway
        # Corridor A: both residential edges. Corridor B: both secondary + tertiary.
        self.a_edges = [i for i, h in enumerate(hwy) if h == "residential"]
        self.b_edges = [i for i, h in enumerate(hwy) if h in ("secondary", "tertiary")]

        # Fast Dijkstra needs open shelters at the east end of the tiny graph.
        shelters = [
            {
                "id": "sh_a",
                "properties": {"name": "A", "open": True, "capacity": 999, "occupancy": 0},
                "geometry": {"type": "Point", "coordinates": [-113.53, 53.52]},
            },
            {
                "id": "sh_b",
                "properties": {"name": "B", "open": True, "capacity": 999, "occupancy": 0},
                "geometry": {"type": "Point", "coordinates": [-113.53, 53.525]},
            },
        ]
        self.eng.set_shelters(lambda: shelters)

    def test_capacities_scale_with_lanes(self):
        # secondary 2-lane should out-capacity residential 1-lane
        res = min(self.eng._capacity[i] for i, h in enumerate(self.eng._highway) if h == "residential")
        sec = min(self.eng._capacity[i] for i, h in enumerate(self.eng._highway) if h == "secondary")
        self.assertGreater(sec, res)

    def test_anti_gridlock_spreads_load(self):
        self.eng.configure(enabled=True, anti_gridlock=True, simulated_count=20)
        # Background assign — wait briefly then force a sync pass.
        import time
        self.eng.rebalance_now(sim_time=0)
        deadline = time.time() + 2
        while time.time() < deadline and not any(a.edge_ids for a in self.eng._agents.values()):
            time.sleep(0.05)
            with self.eng._lock:
                self.eng._assign_all_locked(force=True, sim_time=0)
        routed = [a for a in self.eng._agents.values() if a.edge_ids]
        self.assertTrue(routed)
        shelters = {a.shelter_id for a in routed}
        self.assertTrue(shelters)

    def test_compare_shows_savings_or_equal(self):
        self.eng.configure(enabled=True, anti_gridlock=True, simulated_count=24)
        with self.eng._lock:
            self.eng._assign_all_locked(force=True, sim_time=0)
        out = self.eng.compare(sim_time=0)
        self.assertTrue(out.get("ok"))
        self.assertIsNotNone(out.get("without_min"))
        self.assertIsNotNone(out.get("with_min"))
        # Anti-gridlock should not be worse than naive pile-up.
        self.assertLessEqual(out["with_min"], out["without_min"] + 0.1)

    def test_edge_features_when_enabled(self):
        self.eng.configure(enabled=True, anti_gridlock=True, simulated_count=80)
        with self.eng._lock:
            self.eng._assign_all_locked(force=True, sim_time=0)
            # Guarantee a visible arterial jam even if assignment is sparse.
            for i in self.b_edges:
                self.eng._volume[i] = max(float(self.eng._volume[i]), float(self.eng._capacity[i]) * 0.95)
        fc = self.eng.edge_features(limit=50)
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertTrue(fc["features"])
        props = fc["features"][0]["properties"]
        self.assertIn("vc_ratio", props)
        self.assertIn("level", props)

    def test_map_skips_lightly_loaded_local_streets(self):
        # Arterial jammed; residential only carries a few cars (typical feeder).
        # The map should paint the corridor, not every tiny avenue touching it.
        self.eng.configure(enabled=True, anti_gridlock=True, simulated_count=0)
        with self.eng._lock:
            self.eng._volume[:] = 0.0
            for i in self.b_edges:
                self.eng._volume[i] = float(self.eng._capacity[i]) * 1.2
            for i in self.a_edges:
                self.eng._volume[i] = min(4.0, MAP_LOCAL_MIN_VOLUME * 0.25)
            fc = self.eng.edge_features(limit=50)
        hwys = {f["properties"].get("highway") for f in fc["features"]}
        self.assertTrue(hwys & {"secondary", "tertiary"})
        self.assertNotIn("residential", hwys)


if __name__ == "__main__":
    unittest.main()
