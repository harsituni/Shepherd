"""Road endpoints are explicit, reachable, and evaluated at the same point.

Both ends of a journey are road points: the shelter's designated one and the
person's nearest one. The gaps to the building and the person are reported,
never driven, drawn or timed."""
from unittest.mock import patch
import numpy as np
import pytest
from backend.routing import router
from backend.routing.tests.helpers import Forecast, grid_around, ll, local_graph, shelter


def run(graph, fc=None):
    destination = shelter('rec', ll(2000, 100))
    destination['properties']['routing_endpoint'] = 'reachable_road_point'
    with patch.object(router, '_graph', graph), patch.object(router, '_backup_mode', False):
        router.forget_road_graph()
        try:
            lon, lat = ll(0, 0)
            return router.find_routes(lat, lon, fc, [destination])
        finally:
            router.forget_road_graph()


def test_nearest_disconnected_road_is_not_designated():
    graph = local_graph({'S': (0, 0), 'T': (3000, 0), 'X': (1500, 90), 'Y': (2500, 90)},
                        [('S', 'T', 3000), ('X', 'Y', 1000)])
    body = run(graph)
    o = body['options'][0]
    assert body['route_status'] == 'viable'
    dest = o['access']['destination']
    assert dest['kind'] == 'designated_road_point'
    assert dest['building_point'] == list(ll(2000, 100))
    assert dest['building_access_verified'] is False
    np.testing.assert_allclose(dest['point'], ll(2000, 0), atol=1e-10)
    assert o['geometry']['coordinates'][-1] == dest['point']
    assert o['distance_km'] == 2 and o['eta_min'] == 4
    assert o['arrival_sim_min'] == o['modeled_duration_min']


def test_endpoint_hazard_and_unknown_and_expiry_remain_enforced():
    graph = local_graph({'S': (0, 0), 'T': (3000, 0)}, [('S', 'T', 3000)])
    fc = Forecast(grid_around([ll(0, 0), ll(3000, 100)]))
    assert run(graph, fc.oracle())['route_status'] == 'viable'
    # The building itself is outside the journey. The road endpoint is not.
    fc.at_point(ll(2000, 0), 0)
    assert run(graph, fc.oracle())['no_safe_route'] is True
    fc.at_point(ll(2000, 0), np.nan)
    assert run(graph, fc.oracle())['route_status'] == 'indeterminate'
    fc.arrival[:] = np.inf
    assert run(graph, fc.oracle(covers_until=93))['route_status'] == 'indeterminate'
    option = run(graph, fc.oracle(covers_until=94))['options'][0]
    assert option['status'] == 'tight' and option['leave_by_sim_min'] is None


def journey(graph, pin, target, fc=None):
    destination = shelter('rec', ll(*target))
    destination['properties']['routing_endpoint'] = 'reachable_road_point'
    with patch.object(router, '_graph', graph), patch.object(router, '_backup_mode', False):
        router.forget_road_graph()
        try:
            lon, lat = ll(*pin)
            return router.find_routes(lat, lon, fc, [destination])
        finally:
            router.forget_road_graph()


def two_way(*pairs):
    return [e for u, v, m in pairs for e in ((u, v, m), (v, u, m))]


def test_start_is_the_nearest_road_point_and_the_walk_is_not_driven():
    graph = local_graph({'S': (0, 0), 'T': (3000, 0)}, [('S', 'T', 3000)])
    body = journey(graph, (500, 80), (2000, 100))
    o = body['options'][0]
    assert body['route_status'] == 'viable' and o['status'] == 'ok'
    start, end = o['access']['origin'], o['access']['destination']
    assert start['kind'] == end['kind'] == 'designated_road_point'
    assert start['person_point'] == list(ll(500, 80)) and start['person_access_verified'] is False
    np.testing.assert_allclose(start['point'], ll(500, 0), atol=1e-10)
    assert start['unmodeled_m'] == pytest.approx(80) and end['unmodeled_m'] == pytest.approx(100)
    assert o['geometry']['coordinates'][0] == start['point']
    assert o['geometry']['coordinates'][-1] == end['point']
    assert o['distance_km'] == 1.5 and o['eta_min'] == 3 and o['connector_m'] == 0


def test_two_way_street_start_keeps_both_directions():
    graph = local_graph({'W': (0, 0), 'E': (2000, 0)}, two_way(('W', 'E', 2000)))
    for target, km in (((200, 50), .8), ((1900, 50), .9)):
        o = journey(graph, (1000, 60), target)['options'][0]
        assert o['status'] == 'ok' and o['distance_km'] == pytest.approx(km)


def test_start_skips_a_nearer_road_that_leads_nowhere():
    nodes = {'S': (0, 0), 'T': (1000, 0), 'U': (2000, 0), 'X': (400, 150), 'Y': (600, 150)}
    edges = two_way(('S', 'T', 1000), ('T', 'U', 1000)) + [('X', 'Y', 200)]
    o = journey(local_graph(nodes, edges), (500, 120), (1500, 60))['options'][0]
    np.testing.assert_allclose(o['access']['origin']['point'], ll(500, 0), atol=1e-10)
    assert o['access']['origin']['unmodeled_m'] == pytest.approx(120)  # not the 30 m dead end
    assert o['status'] == 'ok' and o['distance_km'] == pytest.approx(1.)


def test_fire_where_the_person_stands_and_at_the_start_still_counts():
    graph = local_graph({'S': (0, 0), 'T': (3000, 0)}, [('S', 'T', 3000)])
    fc = Forecast(grid_around([ll(0, 0), ll(3000, 300)]))
    pin, target = (500, 250), (2500, 50)
    assert journey(graph, pin, target, fc.oracle())['route_status'] == 'viable'
    fc.at_point(ll(*pin), 0)  # the person's own cell, 250 m from the road
    o = journey(graph, pin, target, fc.oracle())['options'][0]
    assert o['status'] == 'blocked' and 'already' in o['reason']
    fc.at_point(ll(*pin), np.nan)
    assert journey(graph, pin, target, fc.oracle())['route_status'] == 'indeterminate'
    fc.at_point(ll(*pin), np.inf)
    fc.at_point(ll(500, 0), 0)  # the road point the journey starts from
    assert journey(graph, pin, target, fc.oracle())['options'][0]['status'] == 'blocked'
