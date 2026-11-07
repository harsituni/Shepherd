"""The forecast horizon is "minutes from now", not an absolute sim minute.

Regression: past T+120 every arrival was dropped, so /route lost its leave-by
(phone showed "No deadline yet" next to the fire) and /forecast outlines collapsed.
"""

from backend.sim.wildfire import CELL_M, M_PER_DEG_LAT, WildfireSim
import math


def _sim_at(minutes: int) -> WildfireSim:
    sim = WildfireSim(lat=53.535, lon=-113.663, wind_kmh=30, wind_from_deg=270, fuel_dryness=0.7)
    sim.step(minutes)
    return sim


def _lat_lon(sim: WildfireSim, cell: tuple[int, int]) -> tuple[float, float]:
    col, row = cell
    lat = sim.lat + row * CELL_M / M_PER_DEG_LAT
    lon = sim.lon + col * CELL_M / (M_PER_DEG_LAT * math.cos(math.radians(sim.lat)))
    return lat, lon


def test_arrival_min_after_t120_is_relative_to_now():
    sim = _sim_at(300)
    upcoming = {c: at for c, at in sim._arrival_map(120).items() if sim.minutes < at <= sim.minutes + 120}
    assert upcoming, "fire should still be spreading at T+300 with 30 km/h wind"
    cell, at = min(upcoming.items(), key=lambda kv: kv[1])
    got = sim.arrival_min(*_lat_lon(sim, cell))
    assert got is not None
    assert sim.minutes < got <= sim.minutes + 120


def _bbox_area(ring: list[list[float]]) -> float:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def test_forecast_after_t120_grows_beyond_current_fire():
    sim = _sim_at(300)
    now = _bbox_area(sim.features()[0]["geometry"]["coordinates"][0])
    last = max(sim.forecast(), key=lambda o: o["t_min"])
    assert last["t_min"] == 120
    ahead = _bbox_area(last["geometry"]["coordinates"][0])
    assert ahead > now, "the +120 outline should be bigger than the fire now"


def test_forecast_does_not_change_live_fire():
    sim = _sim_at(300)
    before = set(sim.burning)
    sim.forecast()
    sim.arrival_min(53.55, -113.62)
    assert sim.burning == before
