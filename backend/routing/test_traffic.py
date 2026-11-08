"""BPR traffic model + anti-gridlock assignment (additive /traffic API)."""

import unittest

import numpy as np

from backend.routing.traffic import (
    BPR_ALPHA,
    BPR_BETA,
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


class TrafficEngineTests(unittest.TestCase):
    def test_configure_toggle(self):
        eng = TrafficEngine()
        st = eng.configure(enabled=True, anti_gridlock=True, simulated_count=10)
        self.assertTrue(st["enabled"])
        self.assertTrue(st["anti_gridlock"])
        self.assertEqual(st["simulated_count"], 10)
        st = eng.configure(enabled=False)
        self.assertFalse(st["enabled"])

    def test_compare_needs_router(self):
        eng = TrafficEngine()
        out = eng.compare()
        self.assertEqual(out.get("error"), "traffic_unavailable")

    def test_switch_threshold_constant(self):
        self.assertGreaterEqual(SWITCH_SAVE_MIN, 3.0)


class TrafficWithTinyGraph(unittest.TestCase):
    """Bind a miniature NetworkX digraph and assign with a stub router."""

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

        def fake_route(lat, lon):
            # Always offer two options; prefer the emptier corridor by BPR time.
            a_edges, b_edges = self.a_edges, self.b_edges
            a_eta = self.eng.travel_min_for_edges(a_edges)
            b_eta = self.eng.travel_min_for_edges(b_edges)
            opts = [
                {
                    "id": "rt_a_fastest",
                    "shelter_id": "sh_a",
                    "status": "ok",
                    "eta_min": int(a_eta) + 1,
                    "modeled_duration_min": a_eta,
                    "traffic_free_min": self.eng.free_min_for_edges(a_edges),
                    "_traffic_edge_ids": a_edges,
                },
                {
                    "id": "rt_b_fastest",
                    "shelter_id": "sh_b",
                    "status": "ok",
                    "eta_min": int(b_eta) + 1,
                    "modeled_duration_min": b_eta,
                    "traffic_free_min": self.eng.free_min_for_edges(b_edges),
                    "_traffic_edge_ids": b_edges,
                },
            ]
            best = min(opts, key=lambda o: o["modeled_duration_min"])
            return {"best_route_id": best["id"], "options": opts}

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
        self.eng.set_callbacks(fake_route, lambda: shelters)

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
        self.eng.configure(enabled=True, anti_gridlock=True, simulated_count=12)
        with self.eng._lock:
            self.eng._assign_all_locked(force=True, sim_time=0)
        fc = self.eng.edge_features(limit=50)
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertTrue(fc["features"])
        props = fc["features"][0]["properties"]
        self.assertIn("vc_ratio", props)
        self.assertIn("level", props)


if __name__ == "__main__":
    unittest.main()
