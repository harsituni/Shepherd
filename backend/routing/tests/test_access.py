"""Trip access: where routes start and end must be modelled, or explicitly unknown."""
from unittest.mock import patch

import numpy as np
import pytest

from backend.routing import router
from backend.routing.tests.helpers import Forecast, grid_around, ll, local_graph, shelter


def route(graph, fc, pin, target):
    with patch.object(router, "_graph", graph), patch.object(router, "_backup_mode", False):
        router.forget_road_graph()
        try:
            lon, lat = ll(*pin)
            return router.find_routes(lat, lon, None if fc is None else fc.oracle(),
                                        [shelter("D", ll(*target))])
        finally:
            router.forget_road_graph()


def test_original_missing_approach_is_not_successful_arrival():
    graph = local_graph({"S": (0, 0), "T": (2000, 0)}, [("S", "T", 2000)])
    fc = Forecast(grid_around([ll(0, 0), ll(2000, 1000)]))
    fc.at_point(ll(2000, 500), 0)
    body = route(graph, fc, (0, 0), (2000, 1000))
    assert body["best_route_id"] is None and body["no_safe_route"] is None
    o = body["options"][0]
    assert o["status"] == "indeterminate"
    assert o["access"]["destination"]["status"] == "unverified"
    assert o["eta_min"] is None and o["arrival_sim_min"] is None
    assert o["geometry_scope"] == "modeled_road_portions"


def test_mapped_approach_is_in_geometry_time_and_hazard_checks():
    nodes = {"S": (0, 0), "T": (2000, 0), "D": (2000, 1000)}
    graph = local_graph(nodes, [("S", "T", 2000), ("T", "D", 1000)])
    fc = Forecast(grid_around([ll(*p) for p in nodes.values()]))
    fc.at_point(ll(2000, 500), 0)
    body = route(graph, fc, (0, 0), (2000, 1000))
    assert body["best_route_id"] is None
    o = body["options"][0]
    assert o["status"] == "blocked"
    assert o["geometry"]["coordinates"][-1] == list(ll(2000, 1000))
    assert o["distance_km"] == 3. and o["eta_min"] == 6
    assert o["arrival_sim_min"] == pytest.approx(6.)


def test_midpoint_of_long_directed_edge_is_routable():
    graph = local_graph({"A": (-1000, 0), "T": (1000, 0)}, [("A", "T", 2000)])
    body = route(graph, None, (0, 0), (1000, 0))
    assert body["best_route_id"] is not None
    o = body["options"][0]
    assert o["distance_km"] == 1. and o["eta_min"] == 2
    assert o["geometry"]["coordinates"][0] == list(ll(0, 0))


def test_isolated_node_does_not_hide_nearby_road_access():
    graph = local_graph({"I": (0, 0), "S": (100, 0), "T": (2000, 0)}, [("S", "T", 1900)])
    body = route(graph, None, (0, 0), (2000, 0))
    assert body["best_route_id"] is not None
    origin = body["options"][0]["access"]["origin"]
    np.testing.assert_allclose(origin["road_point"], ll(100, 0), atol=1e-10)
    assert origin["person_access_verified"] is False
    assert origin["unmodeled_m"] == pytest.approx(100)


def test_directed_mid_edge_access_cannot_travel_backwards():
    graph = local_graph({"A": (0, 0), "T": (2000, 0)}, [("A", "T", 2000)])
    with pytest.raises(router.NoRouteError):
        route(graph, None, (1500, 0), (500, 0))


def test_unmapped_origin_connector_is_not_invented_even_without_fire():
    # The journey starts at the road point; the 100 m to it is reported, not driven.
    graph = local_graph({"A": (0, 0), "T": (2000, 0)}, [("A", "T", 2000)])
    body = route(graph, None, (1000, 100), (2000, 0))
    o = body["options"][0]
    assert o["status"] == "ok" and o["access"]["complete"]
    assert o["distance_km"] == pytest.approx(1.) and o["eta_min"] == 2 and o["connector_m"] == 0
    assert o["access"]["origin"]["unmodeled_m"] == pytest.approx(100)
    assert o["access"]["origin"]["person_point"] == list(ll(1000, 100))
    np.testing.assert_allclose(o["geometry"]["coordinates"][0], ll(1000, 0), atol=1e-10)


def test_partial_road_excludes_fire_behind_origin_and_beyond_destination():
    graph = local_graph({'A': (0, 0), 'B': (4000, 0)}, [('A', 'B', 4000)])
    fc = Forecast(grid_around([ll(0, 0), ll(4000, 0)]))
    fc.at_point(ll(500, 0), 0)
    fc.at_point(ll(3500, 0), 0)
    body = route(graph, fc, (1000, 0), (3000, 0))
    o = body['options'][0]
    assert body['route_status'] == 'viable'
    assert o['distance_km'] == 2 and o['arrival_sim_min'] == pytest.approx(4)
    assert o['geometry']['coordinates'][0] == list(ll(1000, 0))
    assert o['geometry']['coordinates'][-1] == list(ll(3000, 0))
    fc.at_point(ll(2500, 0), 0)
    assert route(graph, fc, (1000, 0), (3000, 0))['no_safe_route'] is True


@pytest.mark.parametrize('burn', [(1000, 0), (3000, 0)])
def test_mapped_origin_and_destination_partial_arcs_check_hazards(burn):
    graph = local_graph({'A': (0, 0), 'B': (4000, 0)}, [('A', 'B', 4000)])
    fc = Forecast(grid_around([ll(0, 0), ll(4000, 0)]))
    fc.at_point(ll(*burn), 0)
    o = route(graph, fc, (1000, 0), (3000, 0))['options'][0]
    assert o['status'] == 'blocked' and o['hazard_intercept']


def test_complete_approach_preserves_buffer_and_forecast_reserve():
    graph = local_graph({'A': (0, 0), 'B': (4000, 0)}, [('A', 'B', 4000)])
    fc = Forecast(grid_around([ll(0, 0), ll(4000, 0)]), fill=34)
    assert route(graph, fc, (1000, 0), (3000, 0))['options'][0]['status'] == 'tight'
    fc.arrival[:] = 33.999
    assert route(graph, fc, (1000, 0), (3000, 0))['no_safe_route'] is True
    fc.arrival[:] = np.inf
    # Entire 4-minute journey and existing 90-minute reserve must be covered.
    with patch.object(fc, 'oracle', side_effect=lambda: Forecast.oracle(fc, covers_until=93)):
        assert route(graph, fc, (1000, 0), (3000, 0))['route_status'] == 'indeterminate'
    with patch.object(fc, 'oracle', side_effect=lambda: Forecast.oracle(fc, covers_until=94)):
        o = route(graph, fc, (1000, 0), (3000, 0))['options'][0]
        # The reserve makes it tight; with no fire on it there is no deadline.
        assert o['status'] == 'tight' and o['leave_by_sim_min'] is None


def test_disconnected_crossing_cannot_be_used_as_a_junction():
    graph = local_graph({'A': (-1000, 0), 'B': (1000, 0), 'C': (0, -1000), 'D': (0, 1000)},
                        [('A', 'B', 2000), ('C', 'D', 2000)])
    body = route(graph, None, (0, 0), (0, 1000))
    assert body['route_status'] == 'indeterminate'
    assert 'Ambiguous crossing' in body['options'][0]['access']['origin']['reason']
    with pytest.raises(router.NoRouteError):
        route(graph, None, (-500, 0), (0, 500))


def test_private_road_is_not_a_verified_access_shortcut():
    graph = local_graph({'A': (0, 0), 'B': (2000, 0), 'C': (0, 100), 'D': (2000, 100)},
                        [('A', 'B', 2000), ('C', 'D', 2000)])
    graph['A']['B'][0]['access'] = 'private'
    body = route(graph, None, (1000, 0), (2000, 100))
    # The private road is never driven: the journey starts on the public one.
    o = body['options'][0]
    assert o['access']['origin']['unmodeled_m'] == pytest.approx(100)
    np.testing.assert_allclose(o['geometry']['coordinates'][0], ll(1000, 100), atol=1e-10)
    assert o['distance_km'] == pytest.approx(1.) and o['steps'][0]['instruction'] == 'Continue on C-D Road'


def test_physical_gap_in_graph_geometry_is_explicit_and_not_drawn_as_a_chord():
    from shapely.geometry import LineString
    graph = local_graph({'A': (0, 0), 'B': (1000, 0), 'C': (2000, 0)},
                        [('A', 'B', 1000), ('B', 'C', 1000)])
    graph['B']['C'][0]['geometry'] = LineString([ll(1100, 0), ll(2000, 0)])
    body = route(graph, None, (0, 0), (2000, 0))
    o = body['options'][0]
    assert body['route_status'] == 'indeterminate'
    assert not o['access']['geometry_continuous']
    assert o['geometry']['type'] == 'MultiLineString'
    assert o['eta_min'] is None and o['leave_by_sim_min'] is None


@pytest.mark.parametrize('offset,allowed', [(300, True), (300.01, False)])
def test_access_threshold_is_measured_to_edge_not_vertex(offset, allowed):
    graph = local_graph({'A': (-1000, 0), 'B': (1000, 0)}, [('A', 'B', 2000)])
    if allowed:
        body = route(graph, None, (0, offset), (1000, 0))
        assert body['route_status'] == 'viable'
        assert body['options'][0]['access']['origin']['unmodeled_m'] == pytest.approx(300)
    else:
        with pytest.raises(router.NoRouteError):
            route(graph, None, (0, offset), (1000, 0))


@pytest.mark.parametrize('lat,lon', [(np.nan, -113.5), (53.5, np.inf), (90, -113.5), (53.5, 200)])
def test_invalid_or_outside_origin_is_rejected(lat, lon):
    graph = local_graph({'A': (0, 0), 'B': (2000, 0)}, [('A', 'B', 2000)])
    with patch.object(router, '_graph', graph), patch.object(router, '_backup_mode', False):
        router.forget_road_graph()
        try:
            with pytest.raises(router.NoRouteError):
                router.find_routes(lat, lon, None, [shelter('B', ll(2000, 0))])
        finally:
            router.forget_road_graph()


def test_loop_road_supports_directed_mid_edge_access():
    from shapely.geometry import LineString
    graph = local_graph({'A': (0, 0)}, [])
    graph.add_edge('A', 'A', length=4000., geometry=LineString(
        [ll(0, 0), ll(1000, 0), ll(1000, 1000), ll(0, 1000), ll(0, 0)]))
    body = route(graph, None, (1000, 500), (500, 0))
    o = body['options'][0]
    assert body['route_status'] == 'viable'
    assert o['distance_km'] == 3 and o['eta_min'] == 6
    assert o['geometry']['coordinates'][0] == list(ll(1000, 500))
    assert o['geometry']['coordinates'][-1] == list(ll(500, 0))


def test_partial_multigraph_search_matches_independent_cell_intersections():
    """Exhaustive keyed paths + Shapely cell intersections, not the route judge.

    Both endpoints are inside directed edges; random hazards exercise the
    clipped legs, all parallel corridors, unknown cells, and the shared exits.
    """
    import networkx as nx
    from shapely.geometry import LineString, Point, box
    from backend.routing.road_graph import TO_GRID
    from backend.routing.tests.helpers import ORIGIN_XY

    nodes = {'S': (-1000, 0), 'A': (0, 0), 'B': (2000, 0), 'T': (3000, 0), 'C': (1000, -700)}
    graph = local_graph(nodes, [('S', 'A', 1000), ('A', 'B', 2000), ('B', 'T', 1000),
                                ('A', 'C', 1500), ('C', 'B', 1500)])
    graph.add_edge('A', 'B', length=2600., geometry=LineString([ll(0, 0), ll(1000, 900), ll(2000, 0)]))
    fc = Forecast(grid_around([ll(-1000, -700), ll(3000, 1000)]))
    paths = []
    ox, oy = ORIGIN_XY
    for keyed in nx.all_simple_edge_paths(graph, 'A', 'B'):
        portions = [(LineString([(ox-400, oy), (ox, oy)]), 400.)]
        for u, v, key in keyed:
            edge = graph[u][v][key]
            xy = np.column_stack(TO_GRID.transform(*np.array(edge['geometry'].coords).T))
            portions.append((LineString(xy), edge['length']))
        portions.append((LineString([(ox+2000, oy), (ox+2600, oy)]), 600.))
        checks, offset = [], 0.
        for line, distance in portions:
            # Independent geometric cell traversal: intersect closed raster
            # squares, take the farthest intersecting point along this polyline.
            for flat in range(fc.grid.nrows * fc.grid.ncols):
                cx, cy = fc.grid.centre(flat)
                cut = line.intersection(box(cx-50, cy-50, cx+50, cy+50))
                if cut.is_empty:
                    continue
                parts = list(cut.geoms) if hasattr(cut, 'geoms') else [cut]
                farthest = max(line.project(Point(p))
                               for part in parts for p in part.coords)
                checks.append((flat, (offset + distance*farthest/line.length)/500.))
            offset += distance
        paths.append((offset, checks))
    assert len(paths) == 3
    rng = np.random.default_rng(20261109)
    touched = np.array(sorted({flat for _, checks in paths for flat, _ in checks}))
    outcomes = set()
    for trial in range(45):
        fc.arrival[:] = [np.inf, 0., np.nan][trial] if trial < 3 else np.inf
        if trial >= 3:
            chosen = rng.choice(touched, 8, replace=False)
            fc.arrival[chosen] = rng.choice([0., 32., 37., 50., np.inf, np.nan], len(chosen))
        statuses = []
        for distance, checks in paths:
            blocked = any(np.isfinite(fc.arrival[f]) and fc.arrival[f]-30-t < -1e-6 for f, t in checks)
            unknown = any(np.isnan(fc.arrival[f]) for f, _ in checks)
            statuses.append('blocked' if blocked else 'indeterminate' if unknown else 'viable')
        expected = ('viable' if 'viable' in statuses else
                    'indeterminate' if 'indeterminate' in statuses else 'blocked')
        outcomes.add(expected)
        body = route(graph, fc, (-400, 0), (2600, 0))
        assert body['route_status'] == expected, (trial, statuses, body)
        assert body['search']['complete']
        assert body['no_safe_route'] is {'viable': False, 'indeterminate': None, 'blocked': True}[expected]
        if expected == 'viable':
            best = body['options'][0]
            possible_lengths = [d/1000 for (d, _), status in zip(paths, statuses) if status == 'viable']
            assert best['modeled_distance_km'] in possible_lengths
            assert best['access']['complete']
    assert outcomes == {'viable', 'blocked', 'indeterminate'}


def test_zero_duration_partial_edge_still_clips_spatial_hazards():
    graph = local_graph({'A': (0, 0), 'B': (4000, 0)}, [('A', 'B', 0)])
    fc = Forecast(grid_around([ll(0, 0), ll(4000, 0)]))
    fc.at_point(ll(500, 0), 0)
    fc.at_point(ll(3500, 0), 0)
    assert route(graph, fc, (1000, 0), (3000, 0))['route_status'] == 'viable'
    fc.at_point(ll(2500, 0), 0)
    assert route(graph, fc, (1000, 0), (3000, 0))['route_status'] == 'blocked'
