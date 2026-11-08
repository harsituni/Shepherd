"""Routing v3 scenarios on the real Edmonton road graph and the live wildfire sim.

Scenarios 1-10 of the v3 prompt. Every answer also passes `check_answer`: the line
starts at the pin and then follows graph edges, status agrees with margin_min,
best_route_id is null exactly when every option is blocked, and ids are unique.

Where the prompt's expected outcome needed a setup the real sim doesn't produce,
the test says so and checks the intended behaviour at a setup that does.
"""

from __future__ import annotations

import copy
from unittest.mock import patch

import numpy as np
import pytest

from backend.api.main import SHELTERS
from backend.routing import router
from backend.routing.router import NoRouteError, find_routes_v3
from backend.sim.controller import SimController

FIRE = (53.535, -113.663)          # scenarios 2, 3, 5, 6, 9
UPWIND = (53.535, -113.70)
DOWNWIND = (53.535, -113.64)


@pytest.fixture(scope="module", autouse=True)
def roads():
    with patch.object(router, "_graph", None), patch.object(router, "_backup_mode", False):
        router.forget_road_graph()
        router.load_graph()
        if router._graph is None:
            pytest.skip("the saved Edmonton road graph is not available")
        yield router._road_graph()
    router.forget_road_graph()


def fire(lat, lon, wind_kmh, wind_from_deg) -> SimController:
    c = SimController(weather="dashboard", domain_bbox=router.graph_bbox())
    c.start({"lat": lat, "lon": lon, "wind_kmh": wind_kmh, "wind_from_deg": wind_from_deg})
    return c


def route(c: SimController, pin, shelters=SHELTERS, check_route_id=None) -> dict:
    body = find_routes_v3(*pin, c.oracle(), shelters, sim_time=c.sim_time, check_route_id=check_route_id)
    check_answer(router._road_graph(), body, pin)
    return body


def option(body, route_id):
    return next((o for o in body["options"] if o["id"] == route_id), None)


def check_answer(rg, body, pin):
    options = body["options"]
    assert 2 <= len(options) <= 4
    ids = [o["id"] for o in options]
    assert len(set(ids)) == len(ids)
    all_blocked = all(o["status"] == "blocked" for o in options)
    assert (body["best_route_id"] is None) == all_blocked == body["no_safe_route"]
    if body["best_route_id"] is not None:
        assert ids[0] == body["best_route_id"]
    for o in options:
        margin = o["margin_min"]
        expected = "ok" if margin is None or margin >= 60 else "tight" if margin >= 0 else "blocked"
        assert o["status"] == expected, o
        assert o["forecast_complete"] is True
        follow_roads(rg, o["geometry"]["coordinates"], pin)


def follow_roads(rg, coords, pin):
    """The line is the pin, then the pin's road node, then whole graph edges head to tail."""
    lat, lon = pin
    pts = [tuple(p) for p in coords]
    assert close(pts[0], (lon, lat))
    u = rg.nearest_node(lat, lon)[0]
    i = 0 if close(pts[0], node_ll(rg, u)) else 1
    assert close(pts[i], node_ll(rg, u))
    while i < len(pts) - 1:
        lo, hi = np.searchsorted(rg.edge_u, [u, u + 1])
        for e in range(lo, hi):
            shape = dedupe(map(tuple, rg.edge_coords_ll(e).tolist()))
            # A few OSM shapes start a metre off their node; then the line keeps both points.
            rest = shape[1:] if close(shape[0], pts[i]) else shape
            if not close(shape[0], pts[i], tol=1e-4):
                continue
            if rest and all(i + 1 + k < len(pts) and close(pts[i + 1 + k], p) for k, p in enumerate(rest)):
                i += len(rest)
                u = int(rg.edge_v[e])
                break
        else:
            raise AssertionError(f"point {i} {pts[i]} does not continue along any road from node {u}")


def node_ll(rg, n):
    return float(rg.node_lon[n]), float(rg.node_lat[n])


def close(a, b, tol=1e-9):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def dedupe(points):
    out = []
    for p in points:
        if not out or p != out[-1]:
            out.append(p)
    return out


# 1
def test_no_fire_gives_three_quick_routes():
    body = route(SimController(weather="dashboard"), (53.535, -113.62))
    assert len(body["options"]) == 3
    assert all(o["status"] == "ok" and o["margin_min"] is None for o in body["options"])
    assert body["best_route_id"] == min(body["options"], key=lambda o: o["eta_min"])["id"]
    assert body["forecast"] is None and body["leave_by_sim_min"] is None


# 2
def test_upwind_of_the_fire_every_usable_route_is_ok():
    # The prompt expects "all ok". Here the usual road to Commonwealth runs east
    # through the fire, so it is shown greyed beside its detour (scenario 3's case);
    # everything the user can pick is ok.
    body = route(fire(*FIRE, 35, 270), UPWIND)
    usable = [o for o in body["options"] if o["status"] != "blocked"]
    assert usable and all(o["status"] == "ok" for o in usable)
    for o in body["options"]:
        if o["status"] == "blocked":
            assert o["role"] == "fastest"
            assert option(body, f"rt_{o['shelter_id']}_safest")["status"] == "ok"


# 3
def test_downwind_pin_must_leave_soon():
    # 2 km downwind every shelter lies further downwind. The fire moves ~45 m/min
    # against a 500 m/min car, so no east-bound road is cut; the start is what's
    # tight, and the answer says how soon to leave.
    c = fire(*FIRE, 35, 270)
    body = route(c, DOWNWIND)
    best = option(body, body["best_route_id"])
    assert best["status"] == "tight"
    assert body["leave_by_sim_min"] == c.sim_time + best["margin_min"]
    assert body["leave_by_label"] == f"Leave within {best['margin_min']} min (sim)"


def test_road_through_the_fire_is_shown_blocked_beside_its_detour():
    # Scenario 3's expectation, where the real fire does cut the fastest road.
    body = route(fire(*FIRE, 35, 270), UPWIND)
    cut = option(body, "rt_sh_commonwealth_fastest")
    detour = option(body, "rt_sh_commonwealth_safest")
    assert cut["status"] == "blocked" and cut["reason"].startswith("Fire is expected on")
    assert cut["hazard_intercept"] is not None
    assert detour["status"] in ("ok", "tight") and detour["rerouted"] is True
    assert body["options"].index(detour) < body["options"].index(cut)


# 4
def test_close_downwind_answers_200_either_way():
    body = route(fire(53.53, -113.60, 40, 270), (53.53, -113.585))
    if body["no_safe_route"]:
        assert all(o["status"] == "blocked" and o["reason"] and o["hazard_intercept"] for o in body["options"])
    else:
        assert option(body, body["best_route_id"])["status"] in ("ok", "tight")


# 5
def test_inside_the_burned_area_every_route_is_already_cut():
    c = fire(*FIRE, 35, 270)
    for _ in range(60):
        c.tick()
    assert c.sim_time == 60
    body = route(c, FIRE)
    assert body["no_safe_route"] is True and body["best_route_id"] is None
    assert all("already on" in o["reason"] for o in body["options"])
    assert "leave_by_label" in body and "shelter_id" not in body  # no flat fields without a best


# 6
def test_picked_route_stays_shown_when_it_turns_blocked():
    pick = "rt_sh_commonwealth_safest"
    c = fire(*FIRE, 35, 270)
    assert route(c, UPWIND, check_route_id=pick)["best_route_id"] == pick
    for _ in range(10):
        c.tick()
    c.set_wind(35, 90)  # the fire now heads for the user
    for _ in range(90):
        body = route(c, UPWIND, check_route_id=pick)
        mine = option(body, pick)
        assert mine is not None
        if mine["status"] == "blocked":
            break
        assert body["best_route_id"] == pick
        c.tick()
    else:
        pytest.fail("the picked route never turned blocked")
    assert body["best_route_id"] != pick
    assert body["best_route_id"] is None or option(body, body["best_route_id"])["status"] != "blocked"


# 7
def test_shelter_the_fire_reaches_soon_ranks_below_safe_ones():
    shelters = copy.deepcopy(SHELTERS)
    for s in shelters:
        s["properties"]["open"] = s["id"] in ("sh_kinsmen", "sh_millwoods")
    pin = (53.51, -113.50)  # Kinsmen is 4 min away, Mill Woods 23

    body = route(fire(53.519, -113.59, 40, 270), pin, shelters)
    near, far = option(body, "rt_sh_kinsmen_fastest"), option(body, "rt_sh_millwoods_fastest")
    assert near["status"] == "ok" and near["eta_min"] < far["eta_min"]
    assert near["shelter_threat_sim_min"] <= body["sim_time"] + near["eta_min"] + 120
    assert far["shelter_threat_sim_min"] is None
    assert body["best_route_id"] == far["id"]

    # Further away the fire reaches Kinsmen too late to matter: the near shelter wins again.
    body = route(fire(53.519, -113.62, 40, 270), pin, shelters)
    assert body["best_route_id"] == "rt_sh_kinsmen_fastest"


# 8
def test_outside_the_demo_area_is_a_404():
    with pytest.raises(NoRouteError, match="demo area"):
        find_routes_v3(53.0, -113.5, None, SHELTERS)


# 9
def test_trip_across_the_city_is_fully_forecast():
    c = fire(*FIRE, 35, 270)
    c.set_speed(16)
    pin = (53.3958, -113.3445)  # south-east edge, ~20 km from the fire
    for _ in range(3):
        body = route(c, pin)
        assert max(o["eta_min"] for o in body["options"]) >= 45
        for o in body["options"]:
            assert body["forecast"]["covers_until_sim_min"] >= body["sim_time"] + o["eta_min"] + 90
        for _ in range(10):
            c.tick()


# 10
def test_paused_sim_gives_identical_answers():
    c = fire(*FIRE, 35, 270)
    for _ in range(5):
        c.tick()
    c.pause()
    first = route(c, DOWNWIND)
    c.tick()
    assert route(c, DOWNWIND) == first
