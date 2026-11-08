"""The forecast horizon is "minutes from now", not an absolute sim minute.

Regression: past T+120 every arrival was dropped, so /route lost its leave-by
(phone showed "No deadline yet" next to the fire) and /forecast outlines collapsed.
"""

import math

from backend.sim.wildfire import WildfireSim

LAT, LON = 53.535, -113.663
M_PER_DEG = 111320


def _sim_at(minutes: int) -> WildfireSim:
    sim = WildfireSim(lat=LAT, lon=LON, wind_kmh=10, wind_from_deg=270, fuel_dryness=0.7)
    sim.step(minutes)
    return sim


def _east_of_ignition(metres: float) -> tuple[float, float]:
    return LAT, LON + metres / (M_PER_DEG * math.cos(math.radians(LAT)))


def test_arrival_min_after_t120_is_relative_to_now():
    sim = _sim_at(300)
    # First point downwind that the fire has not reached yet.
    ahead = next(
        p for p in map(_east_of_ignition, range(0, 4900, 50))
        if (sim.arrival_min(*p, horizon_min=10_000) or 0) > sim.minutes
    )
    got = sim.arrival_min(*ahead)
    assert got is not None, "fire should still be spreading at T+300 with 10 km/h wind"
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
    before = sim.features()
    sim.forecast()
    sim.arrival_min(53.55, -113.62)
    assert sim.features() == before
    assert sim.minutes == 300
