"""Original Codex F02/F04/F05/F10 counterexamples and independent references."""
import math
from unittest.mock import patch

import numpy as np
import networkx as nx
import pytest
from shapely.geometry import LineString

from backend.routing import router
from backend.routing.candidates import safe_search
from backend.routing.road_graph import shortest_paths
from backend.routing.v3_testing import Forecast, grid_around, ll, local_graph, shelter


def routes(graph, fc, shelters, check=None):
    with patch.object(router, "_graph", graph), patch.object(router, "_backup_mode", False):
        router.forget_road_graph()
        try:
            lon, lat = ll(0, 0)
            return router.find_routes_v3(lat, lon, fc.oracle(), shelters, check_route_id=check)
        finally:
            router.forget_road_graph()


def test_f02_only_viable_detour_survives_ninety_percent_overlap():
    nodes = {"S": (0, 0), "A": (9000, 0), "T": (10000, 0), "B": (9500, 2000)}
    graph = local_graph(nodes, [("S", "A", 9000), ("A", "T", 1000),
                                ("A", "B", 2100), ("B", "T", 2100)])
    fc = Forecast(grid_around([ll(*p) for p in nodes.values()]))
    fc.at_point(ll(9500, 0), 0)
    body = routes(graph, fc, [shelter("T", ll(10000, 0))])
    assert body["no_safe_route"] is False
    best = next(o for o in body["options"] if o["id"] == body["best_route_id"])
    assert best["status"] == "ok"
    assert best["distance_km"] == 13.2
    assert list(ll(9500, 2000)) in best["geometry"]["coordinates"]


def test_f04_safe_parallel_road_keeps_its_evaluated_geometry():
    graph = local_graph({"S": (0, 0), "T": (2000, 0)}, [("S", "T", 2000)])
    graph.add_edge("S", "T", length=3200., name="Safe parallel",
                   geometry=LineString([ll(0, 0), ll(1000, 1000), ll(2000, 0)]))
    fc = Forecast(grid_around([ll(0, 0), ll(1000, 1000), ll(2000, 0)]))
    fc.at_point(ll(1000, 0), 0)
    body = routes(graph, fc, [shelter("T", ll(2000, 0))])
    assert body["no_safe_route"] is False
    best = next(o for o in body["options"] if o["id"] == body["best_route_id"])
    assert (best["status"], best["distance_km"], best["eta_min"]) == ("ok", 3.2, 7)
    assert best["geometry"]["coordinates"] == [list(ll(0, 0)), list(ll(1000, 1000)), list(ll(2000, 0))]
    assert best["steps"][0]["instruction"] == "Continue on Safe parallel"
    assert next(o for o in body["options"] if o["role"] == "fastest")["status"] == "blocked"


@pytest.mark.parametrize("hazard", [0., np.nan])
def test_f05_sixth_shelter_is_searched_when_first_five_are_blocked(hazard):
    nodes = {"S": (0, 0)}
    for i in range(6):
        nodes[f"T{i}"] = ((2000 + 400*i)*math.cos(i*math.pi/3),
                          (2000 + 400*i)*math.sin(i*math.pi/3))
    graph = local_graph(nodes, [("S", f"T{i}", 2000 + 400*i) for i in range(6)])
    fc = Forecast(grid_around([ll(*p) for p in nodes.values()]))
    for i in range(5):
        fc.at_point(ll(*(np.array(nodes[f"T{i}"])*.6)), hazard)
    body = routes(graph, fc, [shelter(f"T{i}", ll(*nodes[f"T{i}"])) for i in range(6)])
    assert body["no_safe_route"] is False
    assert body["best_route_id"] == "rt_T5_fastest"
    assert body["search"]["complete"]
    assert body["search"]["shelters_evaluated"] == 6


def cascade():
    pairs = [(0, 1, 1., -1.), (0, 25, 1., np.inf), (25, 1, 2., np.inf)]
    pairs += [(0, k, 3.*k, np.inf) for k in range(2, 25)]
    pairs += [(k, k+1, 1., 3.*k-1.5) for k in range(1, 24)]
    a = np.array(sorted(pairs))
    return a[:, 0].astype(int), a[:, 1].astype(int), a[:, 2], a[:, 3]


def test_f10_cascade_returns_exact_converged_result_without_round_limit():
    u, v, w, deadline = cascade()
    got = safe_search(26, u, v, w, deadline, 0, 0.)
    assert got.converged
    assert got.arrival[24] == 72
    usable = got.allowed & np.isfinite(got.arrival[u])
    assert np.all(got.arrival[u[usable]] <= deadline[usable] + 1e-9)


@pytest.mark.parametrize("compiled_rounds", [1, 20])
def test_multigraph_search_matches_exhaustive_networkx_edge_paths(compiled_rounds):
    """Independent reference enumerates every simple keyed path, not heap labels."""
    rng = np.random.default_rng(80510)
    fallback_count = 0
    for _ in range(200):
        n = int(rng.integers(2, 7))
        pairs = sorted((int(rng.integers(n)), int(rng.integers(n))) for _ in range(3*n))
        pairs = [(u, v) for u, v in pairs if u != v]
        u = np.array([p[0] for p in pairs], dtype=int)
        v = np.array([p[1] for p in pairs], dtype=int)
        w = rng.integers(0, 6, len(pairs)).astype(float)
        deadlines = rng.choice([-np.inf, -1., 0., 1., 3., 8., np.inf], len(pairs))
        t0 = float(rng.integers(0, 3))
        graph = nx.MultiDiGraph()
        graph.add_nodes_from(range(n))
        for e, (a, b) in enumerate(pairs):
            graph.add_edge(a, b, key=e)
        expected = np.full(n, np.inf)
        expected[0] = t0
        for target in range(1, n):
            for path in nx.all_simple_edge_paths(graph, 0, target):
                at = t0
                for _, _, e in path:
                    if at > deadlines[e] + 1e-6:
                        break
                    at += w[e]
                else:
                    expected[target] = min(expected[target], at)
        got = safe_search(n, u, v, w, deadlines, 0, t0, max_rounds=compiled_rounds)
        fallback_count += int(got.used_fallback)
        np.testing.assert_allclose(got.arrival, expected)
        assert got.converged
        for target in range(n):
            path = got.edges_to(0, target)
            if not np.isfinite(expected[target]):
                assert path is None
                continue
            at, node = t0, 0
            for e in path:
                assert u[e] == node and at <= deadlines[e] + 1e-6
                node, at = v[e], at + w[e]
            assert node == target and at == expected[target]
    if compiled_rounds == 1:
        assert fallback_count > 50


def test_per_search_parallel_choice_preserves_weight_geometry_identity():
    u, v = np.array([0, 0, 1]), np.array([1, 1, 2])
    for weights, allowed, expected in [
        ([1., 3., 2.], None, [0, 2]),
        ([9., 3., 2.], None, [1, 2]),
        ([1., 3., 2.], [False, True, True], [1, 2]),
        ([3., 3., 2.], None, [0, 2]),
    ]:
        tree = shortest_paths(3, u, v, np.array(weights), 0,
                              None if allowed is None else np.array(allowed))
        assert tree.edges_to(0, 2).tolist() == expected
        assert tree.distance[2] == sum(weights[e] for e in expected)
        assert shortest_paths(3, u, v, np.array(weights), 2).edges_to(2, 0) is None


def test_blocked_fastest_cannot_hide_unknown_high_overlap_detour():
    nodes = {"S": (0, 0), "A": (9000, 0), "T": (10000, 0), "B": (9500, 2000)}
    graph = local_graph(nodes, [("S", "A", 9000), ("A", "T", 1000),
                                ("A", "B", 2100), ("B", "T", 2100)])
    fc = Forecast(grid_around([ll(*p) for p in nodes.values()]))
    fc.at_point(ll(9500, 0), 0)
    fc.at_point(ll(9250, 1000), np.nan)
    body = routes(graph, fc, [shelter("T", ll(10000, 0))])
    assert body["best_route_id"] is None
    assert body["no_safe_route"] is None
    assert body["route_status"] == "indeterminate"
    assert body["search"]["complete"]
    assert any(o["status"] == "indeterminate" for o in body["options"])


def test_incomplete_search_cannot_claim_all_routes_blocked():
    from backend.routing.candidates import Candidate
    from backend.routing.safety import Judgement
    from backend.routing.select import select
    from types import SimpleNamespace
    c = Candidate(shelter("T", ll(0, 0)), "fastest", SimpleNamespace(total_min=1),
                  Judgement("blocked", -1, -1, None, "Known conflict", None, None, True, 1))
    selected = select(None, [c], search_complete=False)
    assert selected.best is None
    assert selected.no_safe_route is None
    assert selected.route_status == "indeterminate"


def test_complete_pipeline_matches_exhaustive_keyed_paths_with_unknowns():
    """Independent path enumeration; reuse the unchanged judge as the safety contract."""
    from backend.routing.road_graph import RoadGraph, TO_GRID, build_cell_table
    from backend.routing.safety import EdgeFire, RoutePath, judge, viable
    nodes = {"S": (0, 0), "A": (1500, 700), "B": (1500, -700), "T": (3000, 0)}
    graph = local_graph(nodes, [("S", "A", 1700), ("A", "T", 1700),
                                ("S", "B", 1700), ("B", "T", 1700),
                                ("A", "B", 1400), ("B", "A", 1400), ("S", "T", 3000)])
    graph.add_edge("S", "T", length=4000., name="parallel detour",
                   geometry=LineString([ll(0, 0), ll(1500, 1800), ll(3000, 0)]))
    rg = RoadGraph.from_networkx(graph)
    fc = Forecast(grid_around([ll(0, 0), ll(1500, 1800), ll(3000, 0), ll(1500, -700)]))
    table = build_cell_table(rg, fc.grid)
    edge_of = {(rg.node_osmid[u], rg.node_osmid[v], key): e
               for e, (u, v, key) in enumerate(zip(rg.edge_u, rg.edge_v, rg.edge_osm_key))}
    paths = [np.array([edge_of[e] for e in path])
             for path in nx.all_simple_edge_paths(graph, "S", "T")]
    touched = np.unique(table.cell_flat)
    rng = np.random.default_rng(20261108)
    outcomes = set()
    for trial in range(60):
        fc.arrival[:] = [np.inf, 0., np.nan][trial] if trial < 3 else np.inf
        if trial >= 3:
            selected = rng.choice(touched, 12, replace=False)
            fc.arrival[selected] = rng.choice([0., 35., 40., 100., np.inf, np.nan], 12)
        oracle = fc.oracle()
        fire = EdgeFire.for_oracle(rg, table, oracle)
        judgments = []
        for edges in paths:
            path = RoutePath(ll(0, 0), TO_GRID.transform(*ll(0, 0)), ll(0, 0),
                             TO_GRID.transform(*ll(0, 0)), edges, float(rg.edge_len_m[edges].sum()),
                             ll(3000, 0), TO_GRID.transform(*ll(3000, 0)), "T", access_verified=True)
            judgments.append(judge(path, 0., oracle, fire))
        expected = ("viable" if any(viable(j) for j in judgments) else
                    "indeterminate" if any(j.status == "indeterminate" for j in judgments) else "blocked")
        outcomes.add(expected)
        body = routes(graph, fc, [shelter("T", ll(3000, 0))])
        assert body["search"]["complete"]
        assert body["route_status"] == expected
        assert body["no_safe_route"] is {"viable": False, "indeterminate": None, "blocked": True}[expected]
        if expected == "viable":
            best = next(o for o in body["options"] if o["id"] == body["best_route_id"])
            assert best["forecast_complete"] and best["status"] in ("ok", "tight")
    assert outcomes == {"viable", "blocked", "indeterminate"}


def test_zero_time_edges_do_not_change_exact_buffer_feasibility():
    # Several colocated junctions must not accumulate artificial search time.
    nodes = {f"N{i}": (0, 0) for i in range(8)}
    nodes["T"] = (2000, 0)
    graph = local_graph(nodes, [(f"N{i}", f"N{i+1}", 0) for i in range(7)] + [("N7", "T", 2000)])
    fc = Forecast(grid_around([ll(0, 0), ll(2000, 0)]), fill=34.)
    # Force the first colocated node as access; nearest-node ties are outside this test.
    from backend.routing.road_graph import RoadGraph
    original = RoadGraph.nearest_node
    def snap(self, lat, lon):
        if abs(lat - ll(0, 0)[1]) < 1e-9 and abs(lon - ll(0, 0)[0]) < 1e-9:
            return self.node_index("N0"), 0.
        return original(self, lat, lon)
    with patch.object(RoadGraph, "nearest_node", snap):
        body = routes(graph, fc, [shelter("T", ll(2000, 0))])
        fc.arrival[:] = np.nan
        with np.errstate(invalid="raise"):
            unknown = routes(graph, fc, [shelter("T", ll(2000, 0))], check="rt_T_safest")
    assert body["no_safe_route"] is False
    assert body["options"][0]["status"] == "tight"
    assert body["options"][0]["margin_min"] == 0
    assert unknown["no_safe_route"] is None and unknown["best_route_id"] is None
    assert next(o for o in unknown["options"] if o["id"] == "rt_T_safest")["status"] == "indeterminate"
