"""Live wildfire for the API, driven by the FBP spread engine (backend.sim.engine).

Keeps the WildfireSim interface in shared/contract.md: step / features / forecast /
arrival_min / set_wind, wind in km/h and meteorological FROM degrees, and every
outline as one closed Polygon of OUTLINE_POINTS + 1 points (the dashboard blends
outlines point by point, so the count must never change).

How it spreads:
    Canadian FBP System, M-1 boreal mixedwood (50% conifer), BUI 90, flat ground,
    on a 100 m grid filling a 10 x 10 km square around the ignition, widened to
    cover domain_bbox when one is given (the API passes the road graph's box so
    routing has a forecast everywhere it routes). The fire starts as a 300 m
    circle. fuel_dryness sets the fine fuel moisture code (FFMC).

Weather:
    An hourly series from sim minute 0: the OpenWeather forecast when the caller
    passes one (weather=...), else the constructor's wind held constant.
    set_wind() is a manual override: the series is kept up to now and the new wind
    takes over one minute later, so nothing that has already burned changes.

How it runs:
    The engine always computes the whole fire from minute 0 (it has no
    continuation), so the sim holds one finished result that reaches past
    "now + ROUTE_WINDOW_MIN" and swaps in a fresh one when it needs to see further
    ahead or the wind changes. A run takes tens of milliseconds on the 10 km square
    and 0.1-0.2 s across the whole city. Reads use whichever result is current;
    they never wait for a run. oracle() hands routing a frozen snapshot of it.

Usage:
    python -m backend.sim.wildfire                   # ASCII animation, default wind
    python -m backend.sim.wildfire 35 270 0.9        # wind_kmh wind_from_deg fuel_dryness
"""

from __future__ import annotations

import itertools
import math
import threading
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from shapely.geometry import Point, box, mapping

from backend.sim.engine import run_simulation
from backend.sim.engine.contracts import WeatherEntry
from backend.sim.engine.grid import TO_WGS84, seed_mask, to_utm, to_wgs84
from backend.sim.engine.weather import KMH_PER_MS, interpolate_wind
from backend.sim.oracle import ForecastOracle

START_RADIUS_M = 300
MAX_RADIUS_M = 5000           # half-width of the square fire domain around the ignition
CELL_M = 100
OUTLINE_POINTS = 32
FORECAST_STEP_MIN = 15
HORIZON_MIN = 120             # contract default forecast horizon (/forecast, arrival_min)
ROUTE_WINDOW_MIN = 240        # routing judges whole trips: longest drive (~110 min) + 30 buffer + 60
LOOKAHEAD_MIN = 240           # each run reaches this far past what is needed, so runs are rare
INTEGRATION_STEP_MIN = 1.0    # weather only changes hourly or on whole minutes
MAX_WIND_KMH = 60 * KMH_PER_MS
FUEL = {"fuel_type": "M-1", "pc": 50, "bui": 90}


def ffmc_for_dryness(fuel_dryness: float) -> float:
    """Contract fuel_dryness (0-1) to FFMC: 0.7 (the default) gives 92, 0.3 gives 84, 0.95 gives 97.

    A single knob through FFMC's usual fire-season range, not a moisture model.
    """
    dryness = min(max(float(fuel_dryness), 0.0), 1.0)
    return round(min(max(92 + (dryness - 0.7) * 20, 80), 98), 1)


# Fire runs are numbered across every sim in the process, so a forecast version
# never repeats after /sim/reset and routing caches can't mix two fires.
_VERSIONS = itertools.count(1)


class WildfireSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 20,
                 wind_from_deg: float = 315, fuel_dryness: float = 0.7, *,
                 weather: Optional[list[dict]] = None, t0: Optional[datetime] = None,
                 weather_source: Optional[dict] = None, domain_bbox: Optional[list] = None):
        """weather: hourly Contract A entries from sim minute 0 (t_min 0, 60, ...).
        Without it, wind_kmh / wind_from_deg blow constantly.
        domain_bbox: [min_lon, min_lat, max_lon, max_lat] the fire must also cover."""
        self.lat = float(lat)
        self.lon = float(lon)
        self.fuel_dryness = fuel_dryness
        self.ffmc = ffmc_for_dryness(fuel_dryness)
        self.t0 = t0 or datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.minutes = 0
        if weather:
            self._weather = [WeatherEntry.model_validate(w) for w in weather]
            self._override = None
            self.weather_source = dict(weather_source or {"provider": "series"})
        else:
            self._weather = [_entry(0, *_clamp_wind(wind_kmh, wind_from_deg))]
            self._override = _clamp_wind(wind_kmh, wind_from_deg)
            self.weather_source = dict(weather_source or {"provider": "dashboard"})

        centre = to_utm(Point(self.lon, self.lat))
        self._bbox = list(to_wgs84(centre.buffer(MAX_RADIUS_M, cap_style="square")).bounds)
        if domain_bbox is not None:
            d = [float(v) for v in domain_bbox]
            self._bbox = [min(self._bbox[0], d[0]), min(self._bbox[1], d[1]),
                          max(self._bbox[2], d[2]), max(self._bbox[3], d[3])]
        self._perimeter = mapping(to_wgs84(centre.buffer(START_RADIUS_M, quad_segs=16)))
        self._lock = threading.RLock()
        self._runs = 0
        self._version = 0
        self._oracle = None
        self._oracle_arrival = (0, None)   # (version, read-only arrival array)
        self._in_domain = None
        self._run(ROUTE_WINDOW_MIN + LOOKAHEAD_MIN)

    # ---------- wind ----------

    @property
    def wind_kmh(self) -> float:
        return round(self._wind_now()[0], 1)

    @property
    def wind_from_deg(self) -> float:
        return round(self._wind_now()[1], 1)

    def _wind_now(self):
        if self._override is not None:
            return self._override
        speed_ms, from_deg = interpolate_wind(self._weather, self.minutes)
        return speed_ms * KMH_PER_MS, from_deg

    def set_wind(self, wind_kmh: float, wind_from_deg: float) -> None:
        """Dashboard override: from the next minute on, this wind blows constantly."""
        kmh, from_deg = _clamp_wind(wind_kmh, wind_from_deg)
        with self._lock:
            now = self.minutes
            if now == 0:
                self._weather = [_entry(0, kmh, from_deg)]
            else:
                kept = [w for w in self._weather if w.t_min <= now]
                if kept[-1].t_min < now:
                    # Pin the wind at `now` so the minutes already simulated keep their weather.
                    speed_ms, at_deg = interpolate_wind(self._weather, now)
                    kept.append(kept[-1].model_copy(
                        update={"t_min": now, "wind_speed_ms": speed_ms, "wind_dir_deg": at_deg}))
                kept.append(_entry(now + 1, kmh, from_deg, like=kept[-1]))
                self._weather = kept
            self._override = (kmh, from_deg)
            self._run(max(self._result.horizon_min, now + ROUTE_WINDOW_MIN + LOOKAHEAD_MIN))

    # ---------- time ----------

    def step(self, minutes: int) -> None:
        with self._lock:
            self.minutes += minutes
            self._covering(self.minutes + ROUTE_WINDOW_MIN)

    def _covering(self, until_min):
        """The current result, first recomputed further ahead if it ends before until_min."""
        result = self._result
        if result.horizon_min < until_min:
            with self._lock:
                if self._result.horizon_min < until_min:
                    self._run(until_min + LOOKAHEAD_MIN)
                result = self._result
        return result

    def _run(self, horizon_min):
        self._runs += 1
        self._result = run_simulation({
            "schema": "v1",
            "scenario_id": "live-wildfire",
            "run_id": f"live-{self._runs}",
            "t0": self.t0.isoformat(),
            "horizon_min": int(horizon_min),
            "step_min": FORECAST_STEP_MIN,
            "bbox": self._bbox,
            "initial_perimeter": self._perimeter,
            "weather": [w.model_dump() for w in self._weather],
            "weather_end_policy": "hold",
            "integration_step_min": INTEGRATION_STEP_MIN,
            "fbp": {**FUEL, "ffmc": self.ffmc},
            "weather_source": self.weather_source,
        })
        self._version = next(_VERSIONS)

    # ---------- routing ----------

    def oracle(self) -> ForecastOracle:
        """Frozen snapshot of the forecast now, covering at least now + ROUTE_WINDOW_MIN.

        The same object comes back until the sim moves on or reruns, so a paused sim
        hands out one snapshot. Arrays are shared by every snapshot of a run.
        """
        with self._lock:
            result = self._covering(self.minutes + ROUTE_WINDOW_MIN)
            snap = self._oracle
            if snap is not None and snap.version == self._version and snap.sim_time == self.minutes:
                return snap
            if self._oracle_arrival[0] != self._version:
                arrival = np.array(result.arrival_grid("p50"), dtype=np.float64).reshape(-1)
                arrival[np.isnan(arrival)] = np.inf
                arrival.flags.writeable = False
                self._oracle_arrival = (self._version, arrival)
            grid = result.grid
            if self._in_domain is None:
                # The cells the engine can burn: the lon/lat domain box, rasterised.
                mask = seed_mask(to_utm(box(*self._bbox)), grid).reshape(-1).copy()
                mask.flags.writeable = False
                self._in_domain = mask
            kmh, from_deg = self._wind_now()
            self._oracle = ForecastOracle(
                version=self._version, run_id=f"live-{self._runs}", band="p50",
                sim_time=self.minutes, covers_until_sim_min=float(result.horizon_min),
                wind_kmh=round(kmh, 1), wind_from_deg=round(from_deg, 1),
                x0=float(grid.origin_x), y0=float(grid.origin_y), cell_m=float(grid.cell_m),
                nrows=int(grid.rows), ncols=int(grid.cols),
                arrival=self._oracle_arrival[1], in_domain=self._in_domain,
            )
            return self._oracle

    # ---------- contract reads ----------

    def features(self) -> list[dict]:
        now = self.minutes
        ring = self._outline(self._covering(now), now)
        return [{
            "type": "Feature",
            "id": "hz_sim_fire",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }]

    def forecast(self, horizon_min: int = HORIZON_MIN) -> list[dict]:
        """Predicted outline Features at 15-min steps up to horizon_min minutes from now.

        Each item includes top-level ``t_min`` plus a GeoJSON Feature with
        ``zone: "predicted"`` (contract GET /forecast). Does not change the live fire.
        """
        now = self.minutes
        result = self._covering(now + horizon_min)
        outlines = []
        for t_min in range(FORECAST_STEP_MIN, horizon_min + 1, FORECAST_STEP_MIN):
            outlines.append({
                "t_min": t_min,
                "type": "Feature",
                "id": f"fc_{t_min}",
                "properties": {"kind": "wildfire", "t_min": t_min, "zone": "predicted"},
                "geometry": {"type": "Polygon", "coordinates": [self._outline(result, now + t_min)]},
            })
        return outlines

    def arrival_min(self, lat: float, lon: float, horizon_min: int = HORIZON_MIN) -> Optional[int]:
        """Sim minute fire reaches (lat, lon), rounded down, or None if not within
        horizon_min minutes from now (or outside the fire domain)."""
        now = self.minutes
        query = self._covering(now + horizon_min).arrival_at(lat, lon)
        if query.status != "arrival" or query.arrival_min > now + horizon_min:
            return None
        return int(math.floor(query.arrival_min))

    def arrival_status(self, lat: float, lon: float, horizon_min: int = HORIZON_MIN) -> tuple:
        """Like arrival_min, but says why there is no minute:
        ("arrival", minute), ("not_reached", None) = clear for the window, or
        ("outside_domain", None) = no forecast here at all."""
        now = self.minutes
        query = self._covering(now + horizon_min).arrival_at(lat, lon)
        if query.status == "arrival" and query.arrival_min <= now + horizon_min:
            return "arrival", int(math.floor(query.arrival_min))
        if query.status in ("arrival", "not_reached"):
            return "not_reached", None
        return "outside_domain", None

    def _outline(self, result, minute) -> list[list[float]]:
        """Ring around the cells burned by `minute`: from the burned area's centre, the
        farthest burned cell's outer edge in each of OUTLINE_POINTS directions."""
        grid = result.grid
        with np.errstate(invalid="ignore"):
            burned = result.arrival_grid() <= minute
        rows, cols = np.nonzero(burned)
        if rows.size == 0:
            # Degenerate point-ring at ignition so callers always get a polygon.
            return [[self.lon, self.lat]] * (OUTLINE_POINTS + 1)
        xs = grid.origin_x + (cols + 0.5) * grid.cell_m
        ys = grid.origin_y - (rows + 0.5) * grid.cell_m
        cx, cy = xs.mean(), ys.mean()
        reach = np.hypot(xs - cx, ys - cy).max() + grid.cell_m
        dist = np.arange(0, reach, grid.cell_m / 2)
        angles = 2 * np.pi * np.arange(OUTLINE_POINTS) / OUTLINE_POINTS
        east, north = np.sin(angles)[:, None], np.cos(angles)[:, None]
        r = np.floor((grid.origin_y - (cy + dist * north)) / grid.cell_m).astype(int)
        c = np.floor((cx + dist * east - grid.origin_x) / grid.cell_m).astype(int)
        inside = (r >= 0) & (r < grid.rows) & (c >= 0) & (c < grid.cols)
        hit = np.zeros(r.shape, dtype=bool)
        hit[inside] = burned[r[inside], c[inside]]
        last = np.where(hit.any(axis=1), hit.shape[1] - 1 - np.argmax(hit[:, ::-1], axis=1), 0)
        edge = dist[last] + grid.cell_m / 2
        lons, lats = TO_WGS84.transform(cx + edge * east[:, 0], cy + edge * north[:, 0])
        ring = [[round(float(x), 6), round(float(y), 6)] for x, y in zip(lons, lats)]
        ring.append(ring[0])
        return ring


def _clamp_wind(wind_kmh, wind_from_deg):
    return min(max(float(wind_kmh), 0.0), MAX_WIND_KMH), float(wind_from_deg) % 360


def _entry(t_min, wind_kmh, wind_from_deg, like=None) -> WeatherEntry:
    """Weather entry with this wind. Temperature, humidity and rain are carried over
    from `like` (the engine does not use them; FFMC sets fuel moisture)."""
    rest = ({"temp_c": like.temp_c, "rh_pct": like.rh_pct, "precip_mm": like.precip_mm} if like
            else {"temp_c": 20.0, "rh_pct": 30.0, "precip_mm": 0.0})
    return WeatherEntry(t_min=t_min, wind_speed_ms=min(wind_kmh / KMH_PER_MS, 60.0),
                        wind_dir_deg=wind_from_deg, **rest)


def _render(sim, half_cells):
    result = sim._covering(sim.minutes)
    row0, col0 = result.grid.cell_of(*to_utm(Point(sim.lon, sim.lat)).coords[0])
    arrival = result.arrival_grid()
    lines = []
    for r in range(row0 - half_cells, row0 + half_cells + 1):
        lines.append("".join(
            "@" if (r, c) == (row0, col0) else "#" if arrival[r, c] <= sim.minutes else "."
            for c in range(col0 - half_cells, col0 + half_cells + 1)))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import time

    args = [float(a) for a in sys.argv[1:4]]
    sim = WildfireSim(53.535, -113.663, *args)
    for frame in range(31):
        if frame:
            sim.step(10)
        print("\033[2J\033[H", end="")
        print(f"sim_time {sim.minutes} min   wind {sim.wind_kmh} km/h from {sim.wind_from_deg:.0f} deg   "
              f"FFMC {sim.ffmc}   (each cell {CELL_M} m)")
        print(_render(sim, 20))
        time.sleep(0.15)
    ring = sim.features()[0]["geometry"]["coordinates"][0]
    print(f"\nPolygon: {len(ring)} coords, closed={ring[0] == ring[-1]}, first={ring[0]}")
