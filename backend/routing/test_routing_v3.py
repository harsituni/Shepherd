"""Unit tests for routing v3 on tiny synthetic roads and hand-made forecasts."""

import heapq
import math
import unittest
from unittest.mock import patch

import numpy as np

from backend.routing import router
from backend.routing.candidates import (
    MAX_OVERLAP, Candidate, Stats, build_candidates, overlap, roomier_search, safe_search,
)
from backend.routing.road_graph import (
    SPEED_KM_PER_MIN, TO_GRID, FireGrid, RoadGraph, build_cell_table, masked_csr, traverse_segment,
)
from backend.routing.safety import BUFFER_MIN, EdgeFire, judge
from backend.routing.select import rank_key, select
from backend.routing.test_router import fake_graph
from backend.routing.v3_testing import Forecast, grid_around, ll, local_graph, shelter


def unit_grid():
    return FireGrid(0.0, 1000.0, 100.0, 10, 10)


def at(gx, gy):
    """Grid units -> metres on unit_grid()."""
    return gx * 100.0, 1000.0 - gy * 100.0


def cells(flat, grid):
    return [divmod(int(f), grid.ncols) for f in flat]


class RoadGraphTests(unittest.TestCase):
    def setUp(self):
        self.rg = RoadGraph.from_networkx(fake_graph())

    def test_parallel_edges_preserved_with_minimum_plain_distance(self):
        u, v = self.rg.node_index(1), self.rg.node_index(2)
        pair = (self.rg.edge_u == u) & (self.rg.edge_v == v)
        self.assertEqual(sorted(self.rg.edge_len_m[pair]), [300.0, 900.0])
        e = int(self.rg.edge_index(u, v))
        self.assertEqual(self.rg.edge_len_m[e], 300.0)
        # csr_matrix would add the 900 m and 300 m roads together if both went in.
        self.assertAlmostEqual(self.rg.csr_time[u, v], 300.0 / 1000 / SPEED_KM_PER_MIN)

    def test_edges_sorted_and_directed(self):
        self.assertTrue(np.all(np.diff(self.rg.edge_key) >= 0))
        identities = list(zip(self.rg.edge_u, self.rg.edge_v, self.rg.edge_osm_key))
        self.assertEqual(len(identities), len(set(identities)))
        n1, n3 = self.rg.node_index(1), self.rg.node_index(3)
        self.assertEqual(self.rg.csr_time[n3, n1], 0)  # no road back from 3 to 1
        with self.assertRaises(KeyError):
            self.rg.edge_index(n3, n1)

    def test_self_loops_retained_for_mid_edge_access_and_geometry_runs_u_to_v(self):
        graph = fake_graph()
        graph.add_edge(4, 4, length=50.0)
        rg = RoadGraph.from_networkx(graph)
        self.assertEqual(int(np.sum(rg.edge_u == rg.edge_v)), 1)
        e = int(rg.edge_index(rg.node_index(1), rg.node_index(2)))
        coords = rg.edge_coords_ll(e)
        self.assertEqual(coords[0].tolist(), [-113.50, 53.54])  # stored 2 -> bend -> 1, reversed
        self.assertEqual(coords[-1].tolist(), [-113.49, 53.54])

    def test_nearest_node(self):
        node, dist = self.rg.nearest_node(53.5401, -113.4901)
        self.assertEqual(self.rg.node_osmid[node], 2)
        self.assertLess(dist, 20)

    def test_masked_csr_never_sums_duplicates(self):
        u = np.array([0, 0, 1]); v = np.array([1, 2, 2]); w = np.array([1.0, 5.0, 1.0])
        m = masked_csr(3, u, v, w, np.array([True, False, True]))
        self.assertEqual(m.nnz, 2)
        self.assertEqual(m[0, 1], 1.0)


class TraversalTests(unittest.TestCase):
    def test_road_clipping_a_cell_for_28_m_is_caught(self):
        grid = unit_grid()
        a, b = at(1.6, 2.6), at(2.4, 1.8)
        flat, enter, leave = traverse_segment(a, b, grid)
        found = dict(zip(cells(flat, grid), zip(enter, leave)))
        self.assertIn((2, 2), found)
        self.assertAlmostEqual(found[(2, 2)][1] - found[(2, 2)][0], 0.25 * math.hypot(80, 80), places=6)
        # v2 split each line into ceil(length / 120) steps and sampled the step ends
        # (router._line_samples): this 113 m segment got only its two ends.
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, math.ceil(length / 120))
        samples = [(a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps) for k in range(steps + 1)]
        self.assertEqual(len(samples), 2)
        self.assertNotIn(2 * grid.ncols + 2, {grid.flat_of(x, y) for x, y in samples})

    def test_corner_crossing_lists_all_four_cells(self):
        grid = unit_grid()
        flat, enter, leave = traverse_segment(at(1.5, 1.5), at(2.5, 2.5), grid)
        self.assertEqual(set(cells(flat, grid)), {(1, 1), (1, 2), (2, 1), (2, 2)})
        self.assertEqual(cells(flat, grid)[0], (1, 1))
        self.assertEqual(cells(flat, grid)[-1], (2, 2))

    def test_road_on_a_cell_border_lists_both_sides(self):
        grid = unit_grid()
        flat, _, _ = traverse_segment(at(1.5, 2.0), at(3.5, 2.0), grid)
        self.assertEqual(set(cells(flat, grid)), {(r, c) for r in (1, 2) for c in (1, 2, 3)})

    def test_zero_length_and_off_grid(self):
        grid = unit_grid()
        flat, enter, leave = traverse_segment(at(1.5, 1.5), at(1.5, 1.5), grid)
        self.assertEqual(cells(flat, grid), [(1, 1)])
        self.assertEqual((enter[0], leave[0]), (0.0, 0.0))
        flat, _, _ = traverse_segment(at(-0.5, 0.5), at(0.5, 0.5), grid)
        self.assertEqual(flat[0], -1)

    def test_cell_table_covers_every_edge_to_its_full_length(self):
        rg = RoadGraph.from_networkx(fake_graph())
        grid = grid_around([(-113.50, 53.54), (-113.48, 53.55)])
        table = build_cell_table(rg, grid)
        counts = np.diff(table.cell_ptr)
        self.assertTrue(np.all(counts >= 1))
        last = table.cell_leave_m[table.cell_ptr[1:] - 1]
        np.testing.assert_allclose(last, rg.edge_len_m)
        self.assertTrue(np.all(table.cell_flat >= 0))


class SearchTests(unittest.TestCase):
    def test_fixpoint_equals_brute_force_on_300_random_graphs(self):
        rng = np.random.default_rng(2026)
        worst = 0
        for _ in range(300):
            n = int(rng.integers(20, 301))
            pairs = np.unique(rng.integers(0, n, size=(n * 4, 2)), axis=0)
            pairs = pairs[pairs[:, 0] != pairs[:, 1]]
            u, v = pairs[:, 0].astype(np.int32), pairs[:, 1].astype(np.int32)
            w = rng.uniform(0.1, 5.0, len(u))
            deadline = np.where(rng.random(len(u)) < 0.5, np.inf, rng.uniform(0, 30, len(u)))
            got = safe_search(n, u, v, w, deadline, 0, 0.0)
            worst = max(worst, got.rounds)
            expected = brute_force(n, u, v, w, deadline, 0)
            np.testing.assert_allclose(got.arrival, expected)
            self.assertTrue(got.converged)
        self.assertLessEqual(worst, 20)

    def test_plan_cost_ordered_search_missed_a_safe_road(self):
        # S=0, J=1, A=2, X=3. S->J is fast but tight; S->A->J is slow but roomy.
        # J->X must be entered by t=12, so only the fast way to J works.
        u = np.array([0, 0, 1, 2], dtype=np.int32)
        v = np.array([1, 2, 3, 1], dtype=np.int32)
        w = np.array([10.0, 7.0, 2.0, 8.0])
        deadline = np.array([2.0, np.inf, 12.0, np.inf])
        self.assertTrue(math.isinf(plan_cost_ordered(4, u, v, w, deadline, 0)[3]))  # the 2.4 flaw
        safe = safe_search(4, u, v, w, deadline, 0, 0.0)
        self.assertEqual(safe.arrival[3], 12.0)
        roomy_cost, roomy_pred = roomier_search(4, u, v, w, deadline, safe, 0)
        self.assertEqual(int(roomy_pred[1]), 2)  # the roomier pass still prefers the slow way to J


def brute_force(n, u, v, w, deadline, start):
    """Label-setting search that only takes a road when reached by its deadline."""
    out = np.full(n, np.inf)
    out[start] = 0.0
    adj = [[] for _ in range(n)]
    for e in range(len(u)):
        adj[u[e]].append(e)
    heap = [(0.0, start)]
    done = np.zeros(n, bool)
    while heap:
        t, x = heapq.heappop(heap)
        if done[x]:
            continue
        done[x] = True
        for e in adj[x]:
            if t <= deadline[e] + 1e-9 and t + w[e] < out[v[e]]:
                out[v[e]] = t + w[e]
                heapq.heappush(heap, (out[v[e]], v[e]))
    return out


def plan_cost_ordered(n, u, v, w, deadline, start):
    """The 2026-11-07 plan's search: ordered by penalised cost, carrying that label's time."""
    best_cost = np.full(n, np.inf)
    times = np.full(n, np.inf)
    best_cost[start], times[start] = 0.0, 0.0
    heap = [(0.0, 0.0, start)]
    while heap:
        cost, t, x = heapq.heappop(heap)
        if cost > best_cost[x]:
            continue
        for e in np.flatnonzero(u == x):
            if t > deadline[e]:
                continue
            shortfall = max(0.0, 60 - (deadline[e] - t)) / 60
            c = cost + w[e] * (1 + 2 * shortfall)
            if c < best_cost[v[e]]:
                best_cost[v[e]], times[v[e]] = c, t + w[e]
                heapq.heappush(heap, (c, t + w[e], v[e]))
    return times


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.graph = local_graph({"S": (0, 0), "X": (2000, 0)}, [("S", "X", 2000)])
        self.rg = RoadGraph.from_networkx(self.graph)
        self.fc = Forecast(grid_around([ll(0, 0), ll(2000, 0)]))
        self.table = build_cell_table(self.rg, self.fc.grid)

    def path_from(self, pin_ll):
        from backend.routing.safety import RoutePath
        s = int(self.rg.node_index("S"))
        e = self.rg.path_edges([s, int(self.rg.node_index("X"))])
        x_ll = ll(2000, 0)
        return RoutePath(pin_ll, TO_GRID.transform(*pin_ll), (self.rg.node_lon[s], self.rg.node_lat[s]),
                         (self.rg.node_x[s], self.rg.node_y[s]), e, 2000.0, x_ll, TO_GRID.transform(*x_ll), "X", access_verified=True)

    def judged(self, pin_ll=None, t_now=0):
        oracle = self.fc.oracle(sim_time=t_now)
        fire = EdgeFire.for_oracle(self.rg, self.table, oracle)
        return judge(self.path_from(pin_ll or ll(0, 0)), t_now, oracle, fire), fire

    def test_deadline_is_latest_entry_time(self):
        mid = self.fc.at_point(ll(1050, 0), 100)
        _, fire = self.judged()
        start = self.table.cell_ptr[0]
        rows = np.flatnonzero(self.table.cell_flat[start:self.table.cell_ptr[1]] == mid)
        leave_m = self.table.cell_leave_m[start + rows[0]]
        self.assertAlmostEqual(fire.edge_deadline[0], 100 - BUFFER_MIN - leave_m / 1000 / SPEED_KM_PER_MIN)

    def test_statuses_and_intercepts(self):
        self.fc.at_point(ll(1050, 0), 100)
        j, _ = self.judged()
        self.assertEqual(j.status, "ok")
        self.assertGreaterEqual(j.margin_min, 60)
        self.fc.at_point(ll(1050, 0), 50)
        j, _ = self.judged()
        self.assertEqual(j.status, "tight")
        self.assertEqual(j.hazard_intercept["road_name"], "S-X Road")
        self.fc.at_point(ll(1050, 0), 25)
        j, _ = self.judged()
        self.assertEqual(j.status, "blocked")
        self.assertTrue(j.reason.startswith("Fire is expected on S-X Road at T+25. Roads close at T-5;"))
        hit = j.hazard_intercept
        self.assertEqual((hit["fire_arrival_sim_min"], hit["closes_at_sim_min"]), (25, -5))
        self.assertAlmostEqual(hit["lat"], ll(1050, 0)[1], places=3)

    def test_fire_on_the_connector_alone_blocks(self):
        pin = ll(-250, 150)  # 290 m from S, off the road
        self.fc.at_point(ll(-150, 90), 0)
        j, _ = self.judged(pin)
        self.assertEqual(j.status, "blocked")
        self.assertEqual(j.hazard_intercept["road_name"], "the connector")
        self.assertEqual(j.reason, "Fire is already on the road by your location.")

    def test_shelter_threat_and_unknown_cells(self):
        self.fc.at_point(ll(2000, 0), 500)
        j, _ = self.judged()
        self.assertEqual((j.status, j.shelter_threat_sim_min, j.forecast_complete), ("ok", 500, True))
        in_domain = np.ones(len(self.fc.arrival), bool)
        in_domain[self.fc.cell(ll(1000, 0))] = False
        oracle = self.fc.oracle(in_domain=in_domain)
        fire = EdgeFire.for_oracle(self.rg, self.table, oracle)
        self.assertFalse(judge(self.path_from(ll(0, 0)), 0, oracle, fire).forecast_complete)

    def test_window_too_short_marks_forecast_incomplete(self):
        oracle = self.fc.oracle(covers_until=60)  # trip ends at T+4, less than 90 min inside
        fire = EdgeFire.for_oracle(self.rg, self.table, oracle)
        with self.assertLogs("backend.routing.safety", "WARNING"):
            self.assertFalse(judge(self.path_from(ll(0, 0)), 0, oracle, fire).forecast_complete)

    def test_no_fire_is_ok_without_margin(self):
        j = judge(self.path_from(ll(0, 0)), 0, None, None)
        self.assertEqual((j.status, j.margin_min, j.hazard_intercept), ("ok", None, None))


class RouterCase(unittest.TestCase):
    """Runs router.find_routes_v3 on a local graph."""
    nodes: dict = {}
    edges: list = []

    def setUp(self):
        self.graph = local_graph(self.nodes, self.edges)
        for name, value in (("_graph", self.graph), ("_backup_mode", False)):
            p = patch.object(router, name, value)
            p.start()
            self.addCleanup(p.stop)
        router.forget_road_graph()
        self.addCleanup(router.forget_road_graph)
        self.fc = Forecast(grid_around([ll(*xy) for xy in self.nodes.values()]))

    def routes(self, shelters, pin=(0, 0), t_now=0, check=None, fire=True):
        lon, lat = ll(*pin)
        oracle = self.fc.oracle(sim_time=t_now) if fire else None
        return router.find_routes_v3(lat, lon, oracle, shelters, check_route_id=check, debug=True)

    def on_edge(self, u, v, fraction, minute):
        (ue, un), (ve, vn) = self.nodes[u], self.nodes[v]
        return self.fc.at_point(ll(ue + (ve - ue) * fraction, un + (vn - un) * fraction), minute)

    def option(self, body, route_id):
        return next(o for o in body["options"] if o["id"] == route_id)


class RoomierFallbackTests(RouterCase):
    # S->X is cut. S->J is fast but tight; S->A->J is slow but roomy;
    # J->X can only be entered in time by the fast way to J.
    nodes = {"S": (0, 0), "X": (4000, 0), "J": (2500, 2500), "A": (0, 3000)}
    edges = [("S", "X", 4000), ("S", "J", 5000), ("S", "A", 3500), ("A", "J", 4000), ("J", "X", 1000)]

    def test_roomier_path_that_judges_blocked_falls_back_to_the_guaranteed_one(self):
        self.on_edge("S", "X", 0.5, 0)
        self.on_edge("S", "J", 0.8, 40.5)
        self.on_edge("J", "X", 0.5, 43)
        body = self.routes([shelter("X", ll(4000, 0))])
        self.assertEqual(body["best_route_id"], "rt_X_safest")
        safest = self.option(body, "rt_X_safest")
        self.assertEqual(safest["status"], "tight")
        self.assertIn(list(ll(2500, 2500)), safest["geometry"]["coordinates"])     # via J
        self.assertNotIn(list(ll(0, 3000)), safest["geometry"]["coordinates"])     # not via A
        self.assertEqual(self.option(body, "rt_X_fastest")["status"], "blocked")
        # The roomier pass alone picks the slow way to J, which arrives too late.
        rg = router._road_graph()
        oracle = self.fc.oracle()
        fire = EdgeFire.for_oracle(rg, router._cell_table(rg, oracle), oracle)
        s = rg.node_index("S")
        safe = safe_search(rg.n_nodes, rg.edge_u, rg.edge_v, rg.edge_weight, fire.edge_deadline, s, 0.0)
        _, pred = roomier_search(rg.n_nodes, rg.edge_u, rg.edge_v, rg.edge_weight, fire.edge_deadline, safe, s)
        self.assertEqual(int(pred[rg.node_index("J")]), rg.node_index("A"))


class RoomierWinsTests(RouterCase):
    # S->X is cut. Via P is shortest but has 5 min spare; via Q is 2 min longer with 70.
    nodes = {"S": (0, 0), "X": (4000, 0), "P": (2000, 1500), "Q": (2000, -2000)}
    edges = [("S", "X", 4000), ("S", "P", 2500), ("P", "X", 2500), ("S", "Q", 3000), ("Q", "X", 3000)]

    def test_safest_prefers_the_road_with_room(self):
        self.on_edge("S", "X", 0.5, 0)
        self.on_edge("S", "P", 0.9, 40)
        self.on_edge("S", "Q", 0.5, 103)
        body = self.routes([shelter("X", ll(4000, 0))])
        safest = self.option(body, "rt_X_safest")
        self.assertIn(list(ll(2000, -2000)), safest["geometry"]["coordinates"])  # via Q
        self.assertEqual(safest["status"], "ok")
        self.assertGreaterEqual(safest["margin_min"], 60)
        self.assertEqual(body["best_route_id"], "rt_X_safest")


class ShelterChoiceTests(RouterCase):
    nodes = {"S": (0, 0), "N": (0, 2000), "P": (300, 0), "Q": (0, -1000)}
    edges = [("S", "N", 2000), ("N", "P", 2100), ("S", "Q", 1000)]

    def test_shelter_near_by_road_beats_near_in_a_straight_line(self):
        body = self.routes([shelter("near_line", ll(300, 0)), shelter("near_road", ll(0, -1000))], fire=False)
        self.assertEqual(body["best_route_id"], "rt_near_road_fastest")
        self.assertEqual([o["shelter_id"] for o in body["options"]], ["near_road", "near_line"])

    def test_no_road_within_300_m(self):
        with self.assertRaises(router.NoRouteError) as raised:
            self.routes([shelter("near_road", ll(0, -1000))], pin=(-400, 0), fire=False)
        self.assertIn("within 300 m", str(raised.exception))

    def test_unmapped_pin_is_explicit_and_not_drawn_as_a_connector(self):
        # The nearest road (S->N, 120 m) is one-way away from Q, so the journey
        # starts on S->Q, 130 m away; neither gap is drawn or driven.
        body = self.routes([shelter("near_road", ll(0, -1000))], pin=(120, 50), fire=False)
        option = body["options"][0]
        origin = option["access"]["origin"]
        self.assertNotEqual(option["geometry"]["coordinates"][0], list(ll(120, 50)))
        self.assertEqual(origin["person_point"], list(ll(120, 50)))
        self.assertEqual(option["geometry"]["coordinates"][0], origin["point"])
        self.assertAlmostEqual(origin["unmodeled_m"], 130, places=3)
        self.assertEqual(option["status"], "ok")
        self.assertEqual(body["best_route_id"], option["id"])
        self.assertEqual((option["distance_km"], option["eta_min"], option["connector_m"]), (1.0, 2, 0))


class FallbackDepthTests(RouterCase):
    nodes = {"S": (0, 0), **{f"E{i}": (1000 * (i + 1) * math.cos(1.2566 * i), 1000 * (i + 1) * math.sin(1.2566 * i))
                             for i in range(5)}}
    edges = [("S", f"E{i}", 1000 * (i + 1)) for i in range(5)]

    def test_three_nearest_shelters_cut_a_farther_one_is_found(self):
        for i in range(3):
            self.on_edge("S", f"E{i}", 0.5, 0)
        shelters = [shelter(f"sh{i}", ll(*self.nodes[f"E{i}"])) for i in range(5)]
        body = self.routes(shelters)
        self.assertFalse(body["no_safe_route"])
        self.assertEqual(body["best_route_id"], "rt_sh3_fastest")
        statuses = {o["shelter_id"]: o["status"] for o in body["options"]}
        self.assertEqual(statuses["sh3"], "ok")
        self.assertEqual(statuses["sh4"], "ok")
        self.assertIn("blocked", statuses.values())  # least-bad cut route still shown


class SelectionTests(RouterCase):
    nodes = {"S": (0, 0), "A": (1500, 0), "B": (0, 1500), "C": (-1500, 0), "D": (0, -1500), "E": (3000, 0)}
    edges = [("S", "A", 1500), ("S", "B", 1500), ("S", "C", 1600), ("S", "D", 1700), ("A", "E", 1500)]

    def test_invariants(self):
        shelters = [shelter(n, ll(*self.nodes[n])) for n in "ABCDE"]
        self.on_edge("S", "B", 0.5, 20)
        body = self.routes(shelters)
        options = body["options"]
        self.assertTrue(2 <= len(options) <= 4)
        self.assertEqual(len({o["id"] for o in options}), len(options))
        counts = {}
        for o in options:
            counts[o["shelter_id"]] = counts.get(o["shelter_id"], 0) + 1
        self.assertLessEqual(max(counts.values()), 2)
        # E's road starts with A's whole road, so only one of them is shown.
        self.assertFalse({"A", "E"} <= set(counts))
        statuses = [o["status"] for o in options]
        self.assertEqual(statuses, sorted(statuses, key=["ok", "tight", "blocked"].index))
        self.assertEqual(body["best_route_id"], options[0]["id"])
        self.assertGreaterEqual(body["timings"]["fixpoint_rounds"], 1)  # the cut road ran the safe search

    def test_overlap_measure(self):
        rg = router._road_graph()
        def cand(path_nodes, name):
            from backend.routing.safety import RoutePath
            edges = rg.path_edges([rg.node_index(n) for n in path_nodes])
            path = RoutePath((0, 0), (0, 0), (0, 0), (0, 0), edges, float(rg.edge_len_m[edges].sum()),
                             (0, 0), (0, 0), name)
            return Candidate(shelter(name, (0, 0)), "fastest", path)
        a, e = cand(["S", "A"], "A"), cand(["S", "A", "E"], "E")
        self.assertEqual(overlap(rg, a, e), 1.0)
        self.assertEqual(overlap(rg, a, cand(["S", "B"], "B")), 0.0)
        self.assertGreater(overlap(rg, a, e), MAX_OVERLAP)


if __name__ == "__main__":
    unittest.main()
