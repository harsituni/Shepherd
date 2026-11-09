"""Forecast validity: absence of evidence cannot establish a viable journey."""

from dataclasses import replace
import json

import numpy as np
import pytest

from backend.routing import router
from backend.routing.safety import EdgeFire
from backend.routing.tests.helpers import Forecast, grid_around, ll, local_graph, shelter


@pytest.fixture
def road(monkeypatch):
    graph = local_graph({"S": (0, 0), "T": (2000, 0)}, [("S", "T", 2000)])
    monkeypatch.setattr(router, "_graph", graph)
    monkeypatch.setattr(router, "_backup_mode", False)
    router.forget_road_graph()
    fc = Forecast(grid_around([ll(0, 0), ll(2000, 0)]))

    def route(oracle, check=None):
        lon, lat = ll(0, 0)
        body = router.find_routes(lat, lon, oracle, [shelter("T", ll(2000, 0))],
                                     check_route_id=check)
        json.dumps(body, allow_nan=False)
        return body

    yield fc, route
    router.forget_road_graph()


def assert_indeterminate(body):
    assert body["best_route_id"] is None
    assert body["no_safe_route"] is None
    assert body["route_status"] == "indeterminate"
    assert body["leave_by_sim_min"] is None
    assert "geometry" not in body  # no flattened recommendation
    assert body["options"]
    for option in body["options"]:
        assert option["status"] == "indeterminate"
        assert option["forecast_complete"] is False
        assert option["reason"]
        assert option["leave_by_sim_min"] is None


@pytest.mark.parametrize("horizon", [1, 33.99, 60, 93.99])
def test_insufficient_horizon_cannot_recommend(road, horizon):
    fc, route = road
    assert_indeterminate(route(fc.oracle(covers_until=horizon), "rt_T_fastest"))


def test_unknown_domain_cannot_recommend(road):
    fc, route = road
    mask = np.ones(len(fc.arrival), bool)
    mask[fc.cell(ll(1050, 0))] = False
    oracle = fc.oracle(in_domain=mask)
    assert_indeterminate(route(oracle))
    rg = router._road_graph()
    fire = EdgeFire.for_oracle(rg, router._cell_table(rg, oracle), oracle)
    assert np.isneginf(fire.edge_deadline[0])


def test_route_outside_raster_is_indeterminate(road):
    fc, route = road
    assert_indeterminate(route(replace(fc.oracle(), x0=fc.grid.x0 + 100_000)))


@pytest.mark.parametrize("bad", [np.nan, -np.inf, -1, 101])
def test_invalid_arrival_is_unknown_not_clear(road, bad):
    fc, route = road
    fc.at_point(ll(1050, 0), bad)
    assert_indeterminate(route(fc.oracle(covers_until=100)))


@pytest.mark.parametrize("fill", [np.nan, -np.inf])
def test_all_invalid_arrivals_are_indeterminate(road, fill):
    fc, route = road
    fc.arrival[:] = fill
    assert_indeterminate(route(fc.oracle()))


def test_original_audit_unknown_and_nan_plus_known_reproductions(road):
    fc, route = road
    assert_indeterminate(route(fc.oracle(in_domain=np.zeros(len(fc.arrival), bool))))
    fc.at_point(ll(1050, 0), np.nan)
    fc.at_point(ll(1550, 0), 100)
    assert_indeterminate(route(fc.oracle()))


@pytest.mark.parametrize("changes", [
    {"covers_until_sim_min": np.nan}, {"covers_until_sim_min": np.inf},
    {"covers_until_sim_min": -1}, {"sim_time": np.nan}, {"sim_time": -1},
    {"cell_m": 0}, {"x0": np.inf}, {"nrows": 0}, {"ncols": 1.5},
    {"crs": "EPSG:4326"}, {"arrival": np.array([0.])},
    {"arrival": np.array(["bad"])}, {"in_domain": np.array([True])},
])
def test_malformed_oracle_is_serializable_indeterminate(road, changes):
    fc, route = road
    body = route(replace(fc.oracle(), **changes))
    assert_indeterminate(body)
    assert body["forecast_error"]


def test_known_blockage_survives_unknown_and_expired_coverage(road):
    fc, route = road
    fc.at_point(ll(500, 0), 0)
    fc.at_point(ll(1500, 0), np.nan)
    body = route(fc.oracle(sim_time=2, covers_until=1))
    assert body["route_status"] == "blocked"
    assert body["no_safe_route"] is True
    assert body["best_route_id"] is None
    option = body["options"][0]
    assert option["status"] == "blocked"
    assert option["hazard_intercept"]["fire_arrival_sim_min"] == 0
    assert option["forecast_complete"] is False


def test_expiry_limits_margin_but_not_the_fire_deadline(road):
    fc, route = road
    fc.at_point(ll(0, 0), 100)
    body = route(fc.oracle(covers_until=100))
    option = body["options"][0]
    assert option["status"] == "tight"
    # Four-minute journey + retained 90-minute reserve: confirmable until T+6, so
    # the margin is 6. Leave-by is the fire's: the start cell burns at 100, less
    # the 30-minute buffer and the drive out of that cell.
    assert option["leave_by_sim_min"] == 69
    assert option["margin_min"] == 6
    assert route(fc.oracle(sim_time=6, covers_until=100))["options"][0]["status"] == "tight"
    assert_indeterminate(route(fc.oracle(sim_time=7, covers_until=100)))


def test_unreached_cells_are_clear_only_within_forecast(road):
    fc, route = road
    body = route(fc.oracle(covers_until=100))
    assert body["route_status"] == "viable"
    assert body["no_safe_route"] is False
    assert body["leave_by_sim_min"] is None  # no fire on the route
    assert body["options"][0]["hazard_intercept"] is None


def test_valid_fire_constraints_and_exact_buffer_are_preserved(road):
    fc, route = road
    for arrival, status, margin in [(100, "ok", 66), (34, "tight", 0), (33.99, "blocked", -1)]:
        fc.arrival[:] = arrival
        body = route(fc.oracle(covers_until=1000))
        option = body["options"][0]
        assert (option["status"], option["margin_min"]) == (status, margin)
        assert option["forecast_complete"]


def test_bad_cells_elsewhere_do_not_invalidate_clear_route(road):
    fc, route = road
    fc.arrival[0] = np.nan  # not on this journey
    assert route(fc.oracle())["options"][0]["status"] == "ok"


def test_selected_indeterminate_option_cannot_replace_viable_recommendation(monkeypatch):
    graph = local_graph({"S": (0, 0), "A": (2000, 0), "B": (0, 2000)},
                        [("S", "A", 2000), ("S", "B", 2000)])
    monkeypatch.setattr(router, "_graph", graph)
    router.forget_road_graph()
    try:
        fc = Forecast(grid_around([ll(0, 0), ll(2000, 0), ll(0, 2000)]))
        fc.at_point(ll(1000, 0), np.nan)
        shelters = [shelter("A", ll(2000, 0)), shelter("B", ll(0, 2000))]
        lon, lat = ll(0, 0)
        for selected in ("rt_A_fastest", "rt_A_safest"):
            body = router.find_routes(lat, lon, fc.oracle(), shelters, check_route_id=selected)
            assert body["best_route_id"] == "rt_B_fastest"
            assert body["route_status"] == "viable" and body["no_safe_route"] is False
            assert next(o for o in body["options"] if o["id"] == selected)["status"] == "indeterminate"
        # One blocked and one unknown does not establish that all candidates are blocked.
        fc.at_point(ll(0, 1000), 0)
        body = router.find_routes(lat, lon, fc.oracle(), shelters)
        assert body["no_safe_route"] is None and body["route_status"] == "indeterminate"
        assert body["best_route_id"] is None
        assert {o["status"] for o in body["options"]} == {"blocked", "indeterminate"}
    finally:
        router.forget_road_graph()


def test_initial_connector_and_shelter_unknowns_are_indeterminate(road):
    fc, route = road
    for point in (ll(0, 0), ll(2000, 0)):
        fc.arrival[:] = np.inf
        fc.at_point(point, np.nan)
        assert_indeterminate(route(fc.oracle()))


def test_replaced_invalid_array_cannot_reuse_valid_cached_constraints(road):
    fc, route = road
    original = fc.oracle()
    assert route(original)["best_route_id"] is not None
    replacement = original.arrival.copy()
    replacement[fc.cell(ll(1050, 0))] = np.nan
    assert_indeterminate(route(replace(original, arrival=replacement)))


def test_every_departure_up_to_deadline_meets_the_fire_limit(road):
    fc, route = road
    # Uniform fire: the limiting cell is at the destination four minutes away.
    assert route(fc.oracle(covers_until=100))["leave_by_sim_min"] is None  # no fire, no deadline
    for horizon, arrival in [(100, 97), (200, 110), (94, 34)]:
        fc.arrival[:] = arrival
        body = route(fc.oracle(covers_until=horizon))
        deadline = body["leave_by_sim_min"]
        assert deadline == int(np.floor(arrival - 30 - 4))
        for departure in (0, deadline / 2, deadline):
            # The fire never cuts the route before the deadline (the forecast
            # window may stop confirming it sooner: indeterminate, not blocked).
            answer = route(fc.oracle(sim_time=departure, covers_until=horizon))
            assert answer["options"][0]["status"] in ("ok", "tight", "indeterminate")
            assert departure + 4 + 30 <= arrival
        later = route(fc.oracle(sim_time=deadline + .01, covers_until=horizon))
        assert later["best_route_id"] is None
        assert later["options"][0]["status"] == "blocked"
