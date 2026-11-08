"""Moving tornado for demos: a fast funnel that tracks the wind and leaves a scar.

Same public surface as WildfireSim (step / features / forecast / arrival_min /
set_wind / oracle) so SimController and routing can treat it as another hazard.

Motion:
    Travels the direction the wind blows TOWARD (FROM + 180°). Ground speed is a
    large fraction of wind_kmh so at demo speeds it can cross Edmonton in minutes
    of sim time. The funnel widens slowly; cells it has already hit stay damaged.
"""

from __future__ import annotations

import itertools
import math
from typing import Optional

import numpy as np

from backend.sim.engine.grid import TO_UTM, TO_WGS84
from backend.sim.oracle import ForecastOracle

OUTLINE_POINTS = 32
FORECAST_STEP_MIN = 15
HORIZON_MIN = 120
ROUTE_WINDOW_MIN = 180
LOOKAHEAD_MIN = 60
MAX_PATH_M = 40000  # keep the arrival grid city-sized even at high demo wind
CELL_M = 100
# Demo-volatile: nearly wind-speed travel so judges see the path race across town.
SPEED_FRAC = 0.9
START_RADIUS_M = 280
GROWTH_M_PER_MIN = 1.5
MAX_RADIUS_M = 900
# Keep the damage corridor readable on the map (wider than the funnel alone).
SCAR_PAD_M = 120
M_PER_DEG_LAT = 111320.0

_VERSIONS = itertools.count(1)


def _clamp_wind(wind_kmh: float, wind_from_deg: float) -> tuple[float, float]:
    return max(0.0, float(wind_kmh)), float(wind_from_deg) % 360.0


def _toward_rad(wind_from_deg: float) -> float:
    return math.radians((wind_from_deg + 180.0) % 360.0)


def _offset_ll(lon: float, lat: float, east_m: float, north_m: float) -> list[float]:
    dlat = north_m / M_PER_DEG_LAT
    dlon = east_m / (M_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat))))
    return [lon + dlon, lat + dlat]


def _circle_ring(lon: float, lat: float, radius_m: float, n: int = OUTLINE_POINTS) -> list[list[float]]:
    ring = []
    for i in range(n):
        a = (i / n) * 2 * math.pi
        ring.append(_offset_ll(lon, lat, radius_m * math.sin(a), radius_m * math.cos(a)))
    ring.append(ring[0])
    return ring


def _capsule_ring(a_lon: float, a_lat: float, b_lon: float, b_lat: float, radius_m: float,
                  n: int = OUTLINE_POINTS) -> list[list[float]]:
    """Stadium outline from A to B with half-width radius_m."""
    ax, ay = TO_UTM.transform(a_lon, a_lat)
    bx, by = TO_UTM.transform(b_lon, b_lat)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1.0:
        return _circle_ring(a_lon, a_lat, radius_m, n)
    px, py = -dy / length, dx / length  # unit perpendicular
    half = max(n // 2, 8)
    pts: list[tuple[float, float]] = []
    for i in range(half + 1):
        t = i / half
        cx, cy = ax + t * dx, ay + t * dy
        pts.append(TO_WGS84.transform(cx + px * radius_m, cy + py * radius_m))
    ang0 = math.atan2(py, px)
    for i in range(1, half):
        a = ang0 + (i / half) * math.pi
        pts.append(TO_WGS84.transform(bx + radius_m * math.cos(a), by + radius_m * math.sin(a)))
    for i in range(half + 1):
        t = 1.0 - i / half
        cx, cy = ax + t * dx, ay + t * dy
        pts.append(TO_WGS84.transform(cx - px * radius_m, cy - py * radius_m))
    for i in range(1, half):
        a = ang0 + math.pi + (i / half) * math.pi
        pts.append(TO_WGS84.transform(ax + radius_m * math.cos(a), ay + radius_m * math.sin(a)))
    pts.append(pts[0])
    return [[float(x), float(y)] for x, y in pts]


class TornadoSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 40,
                 wind_from_deg: float = 270, fuel_dryness: float = 0.7, *,
                 weather=None, t0=None, weather_source: Optional[dict] = None,
                 domain_bbox: Optional[list] = None):
        # fuel_dryness / weather unused — accepted so the controller can call us like WildfireSim.
        del fuel_dryness, weather, t0
        self.lat = float(lat)
        self.lon = float(lon)
        self.wind_kmh, self.wind_from_deg = _clamp_wind(wind_kmh, wind_from_deg)
        self.weather_source = dict(weather_source or {"provider": "dashboard"})
        self.domain_bbox = list(domain_bbox) if domain_bbox else None
        self.minutes = 0
        self._version = next(_VERSIONS)
        self._oracle = None
        self._rebuild_oracle()

    def set_wind(self, wind_kmh: float, wind_from_deg: float) -> None:
        self.wind_kmh, self.wind_from_deg = _clamp_wind(wind_kmh, wind_from_deg)
        self._version = next(_VERSIONS)
        self._oracle = None
        self._rebuild_oracle()

    def step(self, minutes: int) -> None:
        self.minutes += int(minutes)
        # Keep oracle covers_until ahead of routing's window.
        if self._oracle is None or self._oracle.covers_until_sim_min < self.minutes + ROUTE_WINDOW_MIN:
            self._rebuild_oracle()
        else:
            # Refresh snapshot sim_time without rebuilding the whole grid.
            self._oracle = ForecastOracle(
                version=self._oracle.version, run_id=self._oracle.run_id, band="p50",
                sim_time=self.minutes, covers_until_sim_min=self._oracle.covers_until_sim_min,
                wind_kmh=self.wind_kmh, wind_from_deg=self.wind_from_deg,
                x0=self._oracle.x0, y0=self._oracle.y0, cell_m=self._oracle.cell_m,
                nrows=self._oracle.nrows, ncols=self._oracle.ncols,
                arrival=self._oracle.arrival, in_domain=self._oracle.in_domain,
            )

    def _speed_m_per_min(self) -> float:
        return (self.wind_kmh * SPEED_FRAC * 1000.0) / 60.0

    def _radius_at(self, t_min: float) -> float:
        return min(MAX_RADIUS_M, START_RADIUS_M + GROWTH_M_PER_MIN * max(0.0, t_min))

    def _centre_at(self, t_min: float) -> tuple[float, float]:
        """(lon, lat) of the funnel centre at sim minute t_min."""
        toward = _toward_rad(self.wind_from_deg)
        dist = self._speed_m_per_min() * max(0.0, t_min)
        east = dist * math.sin(toward)
        north = dist * math.cos(toward)
        lon, lat = _offset_ll(self.lon, self.lat, east, north)
        return lon, lat

    def features(self) -> list[dict]:
        now = float(self.minutes)
        lon, lat = self._centre_at(now)
        r = self._radius_at(now)
        scar_r = r + SCAR_PAD_M
        features = []
        # Damage already done: corridor from ignition to the funnel now.
        if now > 0.5:
            features.append({
                "type": "Feature",
                "id": "hz_tornado_scar",
                "properties": {"kind": "tornado", "zone": "buffer", "source": "sim"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_capsule_ring(self.lon, self.lat, lon, lat, scar_r)],
                },
            })
        features.append({
            "type": "Feature",
            "id": "hz_tornado_core",
            "properties": {"kind": "tornado", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [_circle_ring(lon, lat, r)]},
        })
        return features

    def forecast(self, horizon_min: int = HORIZON_MIN) -> list[dict]:
        now = float(self.minutes)
        outlines = []
        for t_min in range(FORECAST_STEP_MIN, int(horizon_min) + 1, FORECAST_STEP_MIN):
            lon, lat = self._centre_at(now + t_min)
            r = self._radius_at(now + t_min)
            outlines.append({
                "t_min": t_min,
                "type": "Feature",
                "id": f"fc_{t_min}",
                "properties": {"kind": "tornado", "t_min": t_min, "zone": "predicted"},
                "geometry": {"type": "Polygon", "coordinates": [_circle_ring(lon, lat, r)]},
            })
        return outlines

    def arrival_min(self, lat: float, lon: float, horizon_min: int = HORIZON_MIN) -> Optional[int]:
        status, minute = self.arrival_status(lat, lon, horizon_min)
        return minute if status == "arrival" else None

    def arrival_status(self, lat: float, lon: float, horizon_min: int = HORIZON_MIN) -> tuple:
        oracle = self.oracle()
        x, y = TO_UTM.transform(float(lon), float(lat))
        col = int(math.floor((x - oracle.x0) / oracle.cell_m))
        row = int(math.floor((oracle.y0 - y) / oracle.cell_m))
        if row < 0 or col < 0 or row >= oracle.nrows or col >= oracle.ncols:
            return "outside_domain", None
        flat = row * oracle.ncols + col
        if not oracle.in_domain[flat]:
            return "outside_domain", None
        arrival = float(oracle.arrival[flat])
        if not math.isfinite(arrival) or arrival > self.minutes + horizon_min:
            return "not_reached", None
        return "arrival", int(math.floor(arrival))

    def oracle(self) -> ForecastOracle:
        if self._oracle is None:
            self._rebuild_oracle()
        return self._oracle

    def _rebuild_oracle(self) -> None:
        """Rasterise when each cell is first swallowed by the moving funnel."""
        speed = max(self._speed_m_per_min(), 1.0)
        covers = float(self.minutes + ROUTE_WINDOW_MIN + LOOKAHEAD_MIN)
        # Don't model a track longer than MAX_PATH_M — enough to rip across Edmonton.
        covers = min(covers, self.minutes + MAX_PATH_M / speed)
        travel = min(speed * (covers - self.minutes) + speed * self.minutes, MAX_PATH_M) + MAX_RADIUS_M + 2000
        toward = _toward_rad(self.wind_from_deg)
        end_lon, end_lat = _offset_ll(
            self.lon, self.lat, travel * math.sin(toward), travel * math.cos(toward),
        )
        # Pad a box around the whole corridor.
        pad = MAX_RADIUS_M + 2000
        corners = [
            _offset_ll(self.lon, self.lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ] + [
            _offset_ll(end_lon, end_lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ]
        if self.domain_bbox is not None:
            d = self.domain_bbox
            corners.extend([[d[0], d[1]], [d[2], d[1]], [d[0], d[3]], [d[2], d[3]]])
        lons = [c[0] for c in corners]
        lats = [c[1] for c in corners]
        xs, ys = [], []
        for lon, lat in zip(lons, lats):
            x, y = TO_UTM.transform(lon, lat)
            xs.append(x)
            ys.append(y)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # origin = outer top-left of cell (0,0)
        x0 = math.floor(min_x / CELL_M) * CELL_M
        y0 = math.ceil(max_y / CELL_M) * CELL_M
        ncols = max(1, int(math.ceil((max_x - x0) / CELL_M)))
        nrows = max(1, int(math.ceil((y0 - min_y) / CELL_M)))
        # Cap grid size for hackathon machines.
        while nrows * ncols > 400_000 and CELL_M == 100:
            # Shouldn't happen for Edmonton corridor; shrink by trimming pad via coarser step.
            break
        if nrows * ncols > 500_000:
            ncols = min(ncols, 700)
            nrows = min(nrows, 700)

        arrival = np.full(nrows * ncols, np.inf, dtype=np.float64)
        in_domain = np.ones(nrows * ncols, dtype=bool)

        # Sample often enough that successive footprints overlap (speed can be
        # ~900 m/min at demo wind, while the funnel is only a few hundred metres).
        step = max(0.25, (CELL_M * 0.5) / speed)
        t = 0.0
        while t <= covers + 1e-9:
            clon, clat = self._centre_at(t)
            cx, cy = TO_UTM.transform(clon, clat)
            rad = self._radius_at(t) + CELL_M * 0.75
            rad_sq = rad * rad
            c0 = max(0, int(math.floor((cx - rad - x0) / CELL_M)))
            c1 = min(ncols - 1, int(math.floor((cx + rad - x0) / CELL_M)))
            r0 = max(0, int(math.floor((y0 - (cy + rad)) / CELL_M)))
            r1 = min(nrows - 1, int(math.floor((y0 - (cy - rad)) / CELL_M)))
            for row in range(r0, r1 + 1):
                for col in range(c0, c1 + 1):
                    flat = row * ncols + col
                    cell_x = x0 + (col + 0.5) * CELL_M
                    cell_y = y0 - (row + 0.5) * CELL_M
                    if (cell_x - cx) ** 2 + (cell_y - cy) ** 2 <= rad_sq:
                        if t < arrival[flat]:
                            arrival[flat] = float(t)
            t += step

        arrival.flags.writeable = False
        in_domain.flags.writeable = False
        self._oracle = ForecastOracle(
            version=self._version, run_id=f"tornado-{self._version}", band="p50",
            sim_time=self.minutes, covers_until_sim_min=covers,
            wind_kmh=self.wind_kmh, wind_from_deg=self.wind_from_deg,
            x0=float(x0), y0=float(y0), cell_m=float(CELL_M),
            nrows=int(nrows), ncols=int(ncols),
            arrival=arrival, in_domain=in_domain,
        )
