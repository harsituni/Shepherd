"""ForecastOracle: the frozen forecast snapshot routing reads."""

import math
import threading

import numpy as np
import pytest

from backend.sim.controller import SimController
from backend.sim.engine.grid import TO_UTM
from backend.sim.tests.helpers import arrival_min
from backend.sim.wildfire import LOOKAHEAD_MIN, ROUTE_WINDOW_MIN, WildfireSim

LAT, LON = 53.535, -113.663
GRAPH_BBOX = [-113.782, 53.396, -113.246, 53.632]  # the Edmonton road graph's box


def cell(oracle, lat, lon):
    x, y = TO_UTM.transform(lon, lat)
    row = math.floor((oracle.y0 - y) / oracle.cell_m)
    col = math.floor((x - oracle.x0) / oracle.cell_m)
    return row * oracle.ncols + col


def test_snapshot_matches_the_fire_and_is_read_only():
    sim = WildfireSim(LAT, LON, wind_kmh=30, wind_from_deg=270)
    sim.step(60)
    oracle = sim.oracle()
    assert oracle.sim_time == 60 and oracle.band == "p50"
    assert oracle.covers_until_sim_min >= 60 + ROUTE_WINDOW_MIN
    assert oracle.arrival[cell(oracle, LAT, LON)] == 0.0
    window = int(oracle.covers_until_sim_min) - sim.minutes  # what this snapshot covers, no rerun
    for lat, lon in [(LAT, LON + 0.02), (LAT, LON + 0.06), (LAT, LON - 0.03), (LAT + 0.02, LON)]:
        minute = arrival_min(sim, lat, lon, horizon_min=window)
        got = oracle.arrival[cell(oracle, lat, lon)]
        assert (math.isinf(got) if minute is None else math.floor(got) == minute)
    with pytest.raises(ValueError):
        oracle.arrival[0] = 1.0
    with pytest.raises(ValueError):
        oracle.in_domain[0] = False


def test_outlines_are_the_rings_the_map_draws():
    # Routing draws the evacuation circle from these, so they must be exactly the
    # /hazards ring now and the /forecast ring at +15 min.
    sim = WildfireSim(LAT, LON, wind_kmh=30, wind_from_deg=270)
    sim.step(20)
    oracle = sim.oracle()
    assert not oracle.outlines.flags.writeable
    assert len(oracle.outlines) >= 20 + ROUTE_WINDOW_MIN
    assert np.allclose(oracle.outlines[20], sim.features()[0]["geometry"]["coordinates"][0])
    assert np.allclose(oracle.outlines[35], sim.forecast(15)[0]["geometry"]["coordinates"][0])


def test_same_snapshot_until_time_moves_or_the_fire_reruns():
    sim = WildfireSim(LAT, LON, wind_kmh=20, wind_from_deg=270)
    first = sim.oracle()
    assert sim.oracle() is first  # e.g. while paused
    sim.step(4)
    later = sim.oracle()
    assert later is not first and later.version == first.version
    assert later.arrival is first.arrival  # same run, shared arrays
    sim.set_wind(40, 0)
    turned = sim.oracle()
    assert turned.version > later.version
    assert turned.wind_from_deg == 0.0 and turned.wind_kmh == 40.0


def test_versions_never_repeat_across_sims():
    a = WildfireSim(LAT, LON).oracle().version
    b = WildfireSim(LAT, LON).oracle().version
    assert a != b


def test_window_keeps_covering_the_route_window():
    sim = WildfireSim(LAT, LON, wind_kmh=20, wind_from_deg=270)
    assert sim.oracle().covers_until_sim_min == ROUTE_WINDOW_MIN + LOOKAHEAD_MIN
    for _ in range(30):
        sim.step(16)
        assert sim.oracle().covers_until_sim_min >= sim.minutes + ROUTE_WINDOW_MIN


def test_domain_covers_the_whole_road_graph():
    sim = WildfireSim(LAT, LON, wind_kmh=40, wind_from_deg=270, domain_bbox=GRAPH_BBOX)
    oracle = sim.oracle()
    assert 90_000 < oracle.nrows * oracle.ncols < 2_000_000
    for lat, lon in [(53.40, -113.78), (53.63, -113.25), (53.60, -113.39)]:
        flat = cell(oracle, lat, lon)
        assert 0 <= flat < oracle.nrows * oracle.ncols and oracle.in_domain[flat]
    # Without the box the fire stops 5 km out; with it, it keeps going east.
    sim.step(900)
    assert arrival_min(sim, LAT, LON + 0.09, horizon_min=10_000) is not None


def test_unreached_cells_are_inf_inside_the_domain():
    sim = WildfireSim(LAT, LON, wind_kmh=20, wind_from_deg=270)
    sim.step(60)
    oracle = sim.oracle()
    assert oracle.arrival[cell(oracle, LAT, LON)] == 0.0
    upwind = cell(oracle, LAT, LON - 0.04)
    assert math.isinf(oracle.arrival[upwind]) and oracle.in_domain[upwind]


def test_controller_oracle_follows_the_sim_state():
    c = SimController(weather="dashboard", domain_bbox=GRAPH_BBOX)
    assert c.oracle() is None
    c.start({"lat": LAT, "lon": LON, "wind_kmh": 30, "wind_from_deg": 270})
    first = c.oracle()
    assert first.nrows * first.ncols > 90_000
    c.pause()
    c.tick()
    assert c.oracle() is first
    c.resume()
    c.tick()
    assert c.oracle().sim_time == first.sim_time + c.speed
    c.reset()
    assert c.oracle() is None


def test_a_held_snapshot_never_changes_while_the_sim_moves():
    sim = WildfireSim(LAT, LON, wind_kmh=25, wind_from_deg=270)
    held = sim.oracle()
    copy = held.arrival.copy()
    done = threading.Event()

    def writer():
        for i in range(100):
            sim.step(8)
            if i % 20 == 0:
                sim.set_wind(10 + i % 30, (90 * i) % 360)
        done.set()

    t = threading.Thread(target=writer)
    t.start()
    while not done.is_set():
        np.testing.assert_array_equal(held.arrival, copy)
        assert sim.oracle().covers_until_sim_min >= sim.minutes  # readers never see a gap
    t.join()
    np.testing.assert_array_equal(held.arrival, copy)
