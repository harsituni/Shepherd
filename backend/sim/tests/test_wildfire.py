"""WildfireSim on the FBP engine: contract shapes, spread, wind override, threading."""

import math
import threading

import pytest
from shapely.geometry import Point, Polygon

from backend.sim.tests.helpers import arrival_min
from backend.sim.wildfire import OUTLINE_POINTS, WildfireSim, ffmc_for_dryness

LAT, LON = 53.535, -113.663
M_PER_DEG = 111320
M_PER_DEG_LON = M_PER_DEG * math.cos(math.radians(LAT))


def at(east_m=0.0, north_m=0.0):
    """(lat, lon) this many metres from the ignition."""
    return LAT + north_m / M_PER_DEG, LON + east_m / M_PER_DEG_LON


def ring(sim):
    return sim.features()[0]["geometry"]["coordinates"][0]


def extent(points):
    """Metres the outline reaches east / west / north / south of the ignition."""
    xs = [(x - LON) * M_PER_DEG_LON for x, _ in points]
    ys = [(y - LAT) * M_PER_DEG for _, y in points]
    return {"east": max(xs), "west": -min(xs), "north": max(ys), "south": -min(ys)}


def series(*hours, speed_ms=5.0):
    """Hourly Contract A weather, one wind direction per hour."""
    return [{"t_min": 60 * k, "wind_speed_ms": speed_ms, "wind_dir_deg": d,
             "temp_c": 20.0, "rh_pct": 25.0, "precip_mm": 0.0} for k, d in enumerate(hours)]


def sim_after(minutes, **kwargs):
    sim = WildfireSim(LAT, LON, **kwargs)
    sim.step(minutes)
    return sim


# ---------- contract shapes ----------

def test_features_match_contract():
    (feature,) = WildfireSim(LAT, LON).features()
    assert feature["id"] == "hz_sim_fire"
    assert feature["properties"] == {"kind": "wildfire", "zone": "core", "source": "sim"}
    assert feature["geometry"]["type"] == "Polygon"
    points = feature["geometry"]["coordinates"][0]
    assert len(points) == OUTLINE_POINTS + 1 and points[0] == points[-1]
    lon, lat = points[0]
    assert -114 < lon < -113 and 53 < lat < 54  # [lon, lat], not flipped


def test_every_outline_has_the_same_point_count():
    # dashboard/src/history.js blends outlines point by point; a different count snaps.
    sim = WildfireSim(LAT, LON, wind_kmh=30, wind_from_deg=300)
    for _ in range(5):
        sim.step(45)
        outlines = [ring(sim)] + [o["geometry"]["coordinates"][0] for o in sim.forecast()]
        assert {len(r) for r in outlines} == {OUTLINE_POINTS + 1}


def test_forecast_matches_contract_and_leaves_fire_alone():
    sim = sim_after(30, wind_kmh=25, wind_from_deg=270)
    before = sim.features()
    outlines = sim.forecast()
    assert [o["t_min"] for o in outlines] == [15, 30, 45, 60, 75, 90, 105, 120]
    for o in outlines:
        assert o["id"] == f"fc_{o['t_min']}" and o["type"] == "Feature"
        assert o["properties"] == {"kind": "wildfire", "t_min": o["t_min"], "zone": "predicted"}
    areas = [Polygon(o["geometry"]["coordinates"][0]).area for o in outlines]
    assert areas == sorted(areas) and areas[-1] > Polygon(ring(sim)).area
    assert sim.features() == before and sim.minutes == 30


# ---------- spread ----------

def test_starts_as_a_300_m_circle():
    reach = extent(ring(WildfireSim(LAT, LON)))
    assert all(300 <= m <= 450 for m in reach.values()), reach


def test_spreads_downwind_at_fbp_pace():
    reach = extent(ring(sim_after(120, wind_kmh=20, wind_from_deg=270)))
    # FBP M-1, FFMC 92, BUI 90, 20 km/h: head ~15.4 m/min, plus the 300 m start.
    assert 1700 < reach["east"] < 2600, reach
    assert reach["east"] > 3 * reach["west"]


def test_calm_spreads_evenly():
    reach = extent(ring(sim_after(120, wind_kmh=0)))
    assert max(reach.values()) < 1.2 * min(reach.values()), reach


def test_drier_fuel_spreads_faster():
    wet = extent(ring(sim_after(90, fuel_dryness=0.4, wind_kmh=20, wind_from_deg=270)))
    dry = extent(ring(sim_after(90, fuel_dryness=0.9, wind_kmh=20, wind_from_deg=270)))
    assert dry["east"] > 1.5 * wet["east"]


def test_dryness_maps_onto_ffmc():
    assert [ffmc_for_dryness(d) for d in (0.3, 0.7, 0.95)] == [84.0, 92.0, 97.0]
    assert ffmc_for_dryness(-3) == 80.0 and ffmc_for_dryness(7) == 98.0


def test_fire_stops_at_the_domain_edge():
    sim = sim_after(600, wind_kmh=40, wind_from_deg=270)
    edge = extent(ring(sim))["east"]
    # 5 km half-width, plus the lat/lon bbox of the UTM square and outward cell snapping.
    assert 4800 < edge < 5500
    sim.step(300)
    # The outline is traced from the burned area's centre, which still drifts as the
    # flanks fill in, so the drawn edge may move by up to a cell. The fire itself does not.
    assert abs(extent(ring(sim))["east"] - edge) <= 100
    assert arrival_min(sim, *at(east_m=5600), horizon_min=10_000) is None


# ---------- arrival times ----------

def test_arrival_times():
    sim = sim_after(60, wind_kmh=20, wind_from_deg=270)
    assert arrival_min(sim, LAT, LON) == 0
    burned = arrival_min(sim, *at(east_m=800))
    assert isinstance(burned, int) and 0 < burned <= 60
    coming = arrival_min(sim, *at(east_m=2000))
    assert isinstance(coming, int) and 60 < coming <= 180
    assert arrival_min(sim, *at(north_m=20_000)) is None  # outside the domain
    upwind = at(east_m=-3000)  # backing fire at ~1 m/min: hours away
    assert arrival_min(sim, *upwind) is None
    assert arrival_min(sim, *upwind, horizon_min=10_000) > 180


def test_burned_points_are_inside_the_outline():
    sim = sim_after(150, wind_kmh=25, wind_from_deg=300)
    outline = Polygon(ring(sim)).buffer(150 / M_PER_DEG)  # a cell and a half of slack
    burned = [p for p in (at(e, n) for e in range(-2000, 5000, 250) for n in range(-4000, 2000, 250))
              if (t := arrival_min(sim, *p)) is not None and t <= sim.minutes]
    assert len(burned) > 20
    assert all(outline.contains(Point(lon, lat)) for lat, lon in burned)


# ---------- wind changes ----------

PROBES = [at(e, n) for e in range(-1500, 3000, 200) for n in range(-1500, 1500, 200)]


def test_wind_change_keeps_what_has_burned():
    sim = sim_after(60, wind_kmh=20, wind_from_deg=270)
    before = (sim.features(), [arrival_min(sim, *p) for p in PROBES])
    sim.set_wind(30, 90)
    after = (sim.features(), [arrival_min(sim, *p) for p in PROBES])
    assert after[0] == before[0]
    assert [a for a in after[1] if a is not None and a <= 60] == [b for b in before[1] if b is not None and b <= 60]
    assert (sim.wind_kmh, sim.wind_from_deg) == (30.0, 90.0)


def test_wind_change_turns_the_fire():
    steady, turned = (sim_after(60, wind_kmh=20, wind_from_deg=270) for _ in range(2))
    turned.set_wind(20, 90)
    steady.step(90)
    turned.step(90)
    assert extent(ring(turned))["west"] > 2 * extent(ring(steady))["west"]
    assert extent(ring(turned))["east"] < extent(ring(steady))["east"]


def test_wind_change_at_minute_zero_is_the_starting_wind():
    changed = WildfireSim(LAT, LON, wind_kmh=10, wind_from_deg=0)
    changed.set_wind(25, 270)
    changed.step(60)
    assert ring(changed) == ring(sim_after(60, wind_kmh=25, wind_from_deg=270))


def test_last_wind_change_in_a_minute_wins():
    twice = sim_after(40, wind_kmh=20, wind_from_deg=270)
    twice.set_wind(35, 0)
    twice.set_wind(15, 180)
    once = sim_after(40, wind_kmh=20, wind_from_deg=270)
    once.set_wind(15, 180)
    twice.step(60)
    once.step(60)
    assert ring(twice) == ring(once)


def test_wind_is_clamped_to_what_the_engine_accepts():
    sim = WildfireSim(LAT, LON)
    sim.set_wind(-5, 450)
    assert (sim.wind_kmh, sim.wind_from_deg) == (0.0, 90.0)
    sim.set_wind(500, 0)
    assert sim.wind_kmh == 216.0


def test_seeing_further_ahead_does_not_change_the_past():
    # Many small steps recompute several times; one big step computes once.
    small = WildfireSim(LAT, LON, wind_kmh=15, wind_from_deg=250)
    for _ in range(600):
        small.step(1)
    big = sim_after(600, wind_kmh=15, wind_from_deg=250)
    assert small._runs > big._runs
    assert ring(small) == ring(big)
    assert [arrival_min(small, *p) for p in PROBES] == [arrival_min(big, *p) for p in PROBES]


# ---------- forecast weather ----------

def test_forecast_series_steers_the_fire_and_reports_its_wind():
    # From the west for two hours, then from the north.
    sim = WildfireSim(LAT, LON, wind_kmh=99, wind_from_deg=99,
                      weather=series(270, 270, 0, 0, 0, 0, 0), weather_source={"provider": "openweather"})
    assert (sim.wind_kmh, sim.wind_from_deg) == (18.0, 270.0)  # the series, not the 99s
    sim.step(60)
    early = extent(ring(sim))
    assert early["east"] > 2 * early["south"]
    sim.step(240)
    assert sim.wind_from_deg == 0.0
    late = extent(ring(sim))
    assert late["south"] > 2 * early["south"]
    assert sim.weather_source == {"provider": "openweather"}


def test_override_replaces_the_forecast_from_now_on():
    weather = series(270, 0, 90, 180, 270, 0, 90)
    sim = WildfireSim(LAT, LON, weather=weather)
    sim.step(90)
    before = sim.features()
    sim.set_wind(20, 270)
    assert sim.features() == before
    sim.step(150)
    assert (sim.wind_kmh, sim.wind_from_deg) == (20.0, 270.0)
    held = WildfireSim(LAT, LON, weather=weather)
    held.step(240)
    assert ring(sim) != ring(held)


def test_outside_utm_zone_12_is_rejected():
    with pytest.raises(ValueError, match="UTM zone 12N"):
        WildfireSim(49.28, -123.12)  # Vancouver


# ---------- concurrency ----------

def test_reads_while_ticking_and_changing_wind():
    """The API ticks on the event loop while request threads read and set wind."""
    sim = WildfireSim(LAT, LON, wind_kmh=25, wind_from_deg=270)
    errors, done = [], threading.Event()

    def guard(fn):
        def run():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
                errors.append(exc)
        return run

    @guard
    def writer():
        for i in range(200):
            sim.step(4)
            if i % 25 == 0:
                sim.set_wind(15 + i % 30, (270 + 10 * i) % 360)
        done.set()

    @guard
    def reader():
        while not done.is_set():
            assert len(ring(sim)) == OUTLINE_POINTS + 1
            assert len(sim.forecast()) == 8
            arrival_min(sim, *at(east_m=1500))

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    assert sim.minutes == 800


# ---------- after T+120 (the forecast is relative to now) ----------

def _bbox_area(ring: list[list[float]]) -> float:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def test_forecast_after_t120_grows_beyond_current_fire():
    sim = sim_after(300, wind_kmh=10, wind_from_deg=270)
    now = _bbox_area(sim.features()[0]["geometry"]["coordinates"][0])
    last = max(sim.forecast(), key=lambda o: o["t_min"])
    assert last["t_min"] == 120
    ahead = _bbox_area(last["geometry"]["coordinates"][0])
    assert ahead > now, "the +120 outline should be bigger than the fire now"


def test_forecast_does_not_change_live_fire():
    sim = sim_after(300, wind_kmh=10, wind_from_deg=270)
    before = sim.features()
    sim.forecast()
    sim.oracle()
    assert sim.features() == before
    assert sim.minutes == 300
