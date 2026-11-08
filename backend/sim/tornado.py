"""Supercell tornado for demos — track, life cycle, and damage swath.

Same public surface as WildfireSim (step / features / forecast / arrival_min /
set_wind / oracle) so SimController and routing can treat it as another hazard.

Physics (simplified but grounded):
    • The *storm* translates roughly with the steering wind (FROM + 180°).
    • The tornado sits on the right-rear flank (N. Hemisphere supercell habit)
      and meanders: slow cyclonic curve, along-track sine, and a small wobble.
    • Translation speed is storm-like (tens of km/h), not "balloon at wind speed".
    • Intensity follows a life cycle: organizes → mature → rope-out. Damage width
      scales with that (narrow → violent corridor → thin again).
    • ``core`` = current circulation on the ground; ``buffer`` = debris/rain wrap
      plus the damage already carved along the track.
"""

from __future__ import annotations

import itertools
import math
from typing import Optional

import numpy as np

from backend.sim.engine.grid import TO_UTM, TO_WGS84
from backend.sim.oracle import ForecastOracle

OUTLINE_POINTS = 48
FORECAST_STEP_MIN = 15
HORIZON_MIN = 120
ROUTE_WINDOW_MIN = 180
LOOKAHEAD_MIN = 60
MAX_PATH_M = 45000
CELL_M = 100
M_PER_DEG_LAT = 111320.0

# Life-cycle (sim minutes from touchdown).
ORGANIZE_MIN = 8
MATURE_MIN = 35
DISSIPATE_MIN = 70
# Ground-relative translation: storm motion ≈ 55–75% of steering wind, floored
# so weak dashboard winds still produce a crossing track.
STORM_SPEED_FRAC = 0.65
STORM_SPEED_FLOOR_KMH = 32
STORM_SPEED_CAP_KMH = 85
# Right-rear flank offset from the storm centroid (metres).
FLANK_RIGHT_M = 900
FLANK_BACK_M = 600
# Meander: cyclonic (left-of-track in heading frame → curves to the right of
# the mean path for an eastbound storm) + along-track oscillation.
CURVE_M_PER_KM = 55          # metres of rightward drift per km of travel
SINE_AMP_M = 380
SINE_WAVELENGTH_M = 6500
WOBBLE_AMP_M = 90
# Damage radii (metres) at peak mature stage — EF2–EF3 class corridor for demos.
CORE_R_ORG = 60
CORE_R_PEAK = 320
CORE_R_ROPE = 40
DEBRIS_PAD_M = 450           # rain-wrapped / flying debris around the funnel
SCAR_PAD_M = 80              # extra beyond core for the lasting damage path

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


def _ellipse_ring(lon: float, lat: float, along_m: float, across_m: float,
                  heading_rad: float, n: int = OUTLINE_POINTS) -> list[list[float]]:
    """Ellipse stretched along the heading (funnel leans / smears with motion)."""
    ca, sa = math.cos(heading_rad), math.sin(heading_rad)
    ring = []
    for i in range(n):
        a = (i / n) * 2 * math.pi
        # local: x along-track, y cross-track
        x, y = along_m * math.cos(a), across_m * math.sin(a)
        east = x * sa + y * ca
        north = x * ca - y * sa
        ring.append(_offset_ll(lon, lat, east, north))
    ring.append(ring[0])
    return ring


def _swath_ring(centres: list[tuple[float, float, float]], n_cap: int = 12) -> list[list[float]]:
    """Variable-width damage path. Each centre is (lon, lat, half_width_m)."""
    if not centres:
        return []
    if len(centres) == 1:
        lon, lat, r = centres[0]
        return _circle_ring(lon, lat, r)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, (lon, lat, half) in enumerate(centres):
        ax, ay = TO_UTM.transform(lon, lat)
        if i == 0:
            bx, by = TO_UTM.transform(centres[1][0], centres[1][1])
            dx, dy = bx - ax, by - ay
        elif i == len(centres) - 1:
            px, py = TO_UTM.transform(centres[i - 1][0], centres[i - 1][1])
            dx, dy = ax - px, ay - py
        else:
            p1 = TO_UTM.transform(centres[i - 1][0], centres[i - 1][1])
            p2 = TO_UTM.transform(centres[i + 1][0], centres[i + 1][1])
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        left.append(TO_WGS84.transform(ax + nx * half, ay + ny * half))
        right.append(TO_WGS84.transform(ax - nx * half, ay - ny * half))
    # Round caps at the ends.
    def cap(lon, lat, half, dx, dy, outward_sign):
        length = math.hypot(dx, dy) or 1.0
        ang0 = math.atan2(dy / length, dx / length)  # along track
        # outward perpendicular for the starting side
        base = ang0 + outward_sign * math.pi / 2
        pts = []
        cx, cy = TO_UTM.transform(lon, lat)
        for i in range(1, n_cap):
            a = base + outward_sign * (i / n_cap) * math.pi
            pts.append(TO_WGS84.transform(cx + half * math.cos(a), cy + half * math.sin(a)))
        return pts

    d0x = TO_UTM.transform(centres[1][0], centres[1][1])[0] - TO_UTM.transform(centres[0][0], centres[0][1])[0]
    d0y = TO_UTM.transform(centres[1][0], centres[1][1])[1] - TO_UTM.transform(centres[0][0], centres[0][1])[1]
    dn_x = TO_UTM.transform(centres[-1][0], centres[-1][1])[0] - TO_UTM.transform(centres[-2][0], centres[-2][1])[0]
    dn_y = TO_UTM.transform(centres[-1][0], centres[-1][1])[1] - TO_UTM.transform(centres[-2][0], centres[-2][1])[1]
    start_cap = cap(centres[0][0], centres[0][1], centres[0][2], d0x, d0y, -1)
    end_cap = cap(centres[-1][0], centres[-1][1], centres[-1][2], dn_x, dn_y, 1)
    ring = left + end_cap + list(reversed(right)) + start_cap
    ring.append(ring[0])
    return [[float(x), float(y)] for x, y in ring]


class TornadoSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 40,
                 wind_from_deg: float = 270, fuel_dryness: float = 0.7, *,
                 weather=None, t0=None, weather_source: Optional[dict] = None,
                 domain_bbox: Optional[list] = None):
        del fuel_dryness, weather, t0
        self.lat = float(lat)
        self.lon = float(lon)
        self.wind_kmh, self.wind_from_deg = _clamp_wind(wind_kmh, wind_from_deg)
        self.weather_source = dict(weather_source or {"provider": "dashboard"})
        self.domain_bbox = list(domain_bbox) if domain_bbox else None
        # Deterministic meander phase from the touchdown point (stable across ticks).
        self._phase = ((abs(self.lat) * 1000 + abs(self.lon) * 100) % 6.28)
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
        if self._oracle is None or self._oracle.covers_until_sim_min < self.minutes + ROUTE_WINDOW_MIN:
            self._rebuild_oracle()
        else:
            self._oracle = ForecastOracle(
                version=self._oracle.version, run_id=self._oracle.run_id, band="p50",
                sim_time=self.minutes, covers_until_sim_min=self._oracle.covers_until_sim_min,
                wind_kmh=self.wind_kmh, wind_from_deg=self.wind_from_deg,
                x0=self._oracle.x0, y0=self._oracle.y0, cell_m=self._oracle.cell_m,
                nrows=self._oracle.nrows, ncols=self._oracle.ncols,
                arrival=self._oracle.arrival, in_domain=self._oracle.in_domain,
            )

    def _storm_speed_m_per_min(self) -> float:
        kmh = min(STORM_SPEED_CAP_KMH, max(STORM_SPEED_FLOOR_KMH, self.wind_kmh * STORM_SPEED_FRAC))
        return (kmh * 1000.0) / 60.0

    def _intensity(self, t_min: float) -> float:
        """0..1 life-cycle intensity (organize → mature → dissipate)."""
        t = max(0.0, t_min)
        if t <= ORGANIZE_MIN:
            return 0.15 + 0.55 * (t / ORGANIZE_MIN)
        if t <= MATURE_MIN:
            # Peak in the middle of mature phase.
            u = (t - ORGANIZE_MIN) / max(1.0, MATURE_MIN - ORGANIZE_MIN)
            return 0.7 + 0.3 * math.sin(u * math.pi)
        if t <= DISSIPATE_MIN:
            u = (t - MATURE_MIN) / max(1.0, DISSIPATE_MIN - MATURE_MIN)
            return max(0.08, 1.0 - 0.92 * u)
        # Rope-out remnant, still a thin track.
        return 0.08

    def _core_radius(self, t_min: float) -> float:
        inten = self._intensity(t_min)
        if inten < 0.7:
            # Organize / dissipate: interpolate toward peak width with intensity.
            return CORE_R_ROPE + (CORE_R_PEAK - CORE_R_ROPE) * (inten / 0.7) * 0.55
        return CORE_R_ORG + (CORE_R_PEAK - CORE_R_ORG) * ((inten - 0.5) / 0.5)

    def _damage_half_width(self, t_min: float) -> float:
        return self._core_radius(t_min) + SCAR_PAD_M

    def _heading(self) -> float:
        return _toward_rad(self.wind_from_deg)

    def _centre_at(self, t_min: float) -> tuple[float, float]:
        """Ground circulation centre (lon, lat) at sim minute t_min."""
        t = max(0.0, t_min)
        heading = self._heading()
        along = self._storm_speed_m_per_min() * t
        # Mean storm path.
        east = along * math.sin(heading)
        north = along * math.cos(heading)
        # Right-rear flank of the parent storm (right = +90° from heading).
        right = heading + math.pi / 2
        east += FLANK_RIGHT_M * math.sin(right) - FLANK_BACK_M * math.sin(heading)
        north += FLANK_RIGHT_M * math.cos(right) - FLANK_BACK_M * math.cos(heading)
        # Cyclonic curve: drift to the right of the mean track with distance.
        east += (along / 1000.0) * CURVE_M_PER_KM * math.sin(right)
        north += (along / 1000.0) * CURVE_M_PER_KM * math.cos(right)
        # Along-track / cross-track meander (suction vortices wandering).
        phase = self._phase + along * (2 * math.pi / SINE_WAVELENGTH_M)
        east += SINE_AMP_M * math.sin(phase) * math.sin(right)
        north += SINE_AMP_M * math.sin(phase) * math.cos(right)
        # Small high-frequency wobble.
        w = self._phase * 3.7 + along * 0.012
        east += WOBBLE_AMP_M * math.sin(w) * math.sin(heading)
        north += WOBBLE_AMP_M * math.cos(w * 1.3) * math.cos(heading)
        lon, lat = _offset_ll(self.lon, self.lat, east, north)
        return lon, lat

    def _track_samples(self, t0: float, t1: float, spacing_m: float = 220.0) -> list[tuple[float, float, float]]:
        speed = max(self._storm_speed_m_per_min(), 1.0)
        dt = max(0.35, spacing_m / speed)
        samples = []
        t = max(0.0, t0)
        end = max(t, t1)
        while t <= end + 1e-9:
            lon, lat = self._centre_at(t)
            samples.append((lon, lat, self._damage_half_width(t)))
            t += dt
        if not samples or samples[-1][0] != self._centre_at(end)[0]:
            lon, lat = self._centre_at(end)
            samples.append((lon, lat, self._damage_half_width(end)))
        return samples

    def features(self) -> list[dict]:
        now = float(self.minutes)
        lon, lat = self._centre_at(now)
        core_r = self._core_radius(now)
        heading = self._heading()
        # Funnel footprint: slightly elongated along motion (suction / translation smear).
        along = core_r * 1.25
        across = core_r * 0.85
        features = []
        if now > 1.0:
            scar = _swath_ring(self._track_samples(0.0, now))
            if scar:
                features.append({
                    "type": "Feature",
                    "id": "hz_tornado_scar",
                    "properties": {"kind": "tornado", "zone": "buffer", "source": "sim", "role": "damage_path"},
                    "geometry": {"type": "Polygon", "coordinates": [scar]},
                })
        # Debris / rain-wrapped mesocyclone around the current circulation.
        features.append({
            "type": "Feature",
            "id": "hz_tornado_debris",
            "properties": {"kind": "tornado", "zone": "buffer", "source": "sim", "role": "debris"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_circle_ring(lon, lat, core_r + DEBRIS_PAD_M)],
            },
        })
        features.append({
            "type": "Feature",
            "id": "hz_tornado_core",
            "properties": {
                "kind": "tornado", "zone": "core", "source": "sim",
                "intensity": round(self._intensity(now), 2),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [_ellipse_ring(lon, lat, along, across, heading)],
            },
        })
        return features

    def forecast(self, horizon_min: int = HORIZON_MIN) -> list[dict]:
        """Predicted damage-corridor outlines (uncertainty grows with lead time)."""
        now = float(self.minutes)
        outlines = []
        for t_min in range(FORECAST_STEP_MIN, int(horizon_min) + 1, FORECAST_STEP_MIN):
            # Corridor from now → now+t_min, widened by forecast uncertainty.
            uncertain = 40.0 * (t_min / 15.0)  # metres of extra half-width per 15 min
            samples = []
            for lon, lat, half in self._track_samples(now, now + t_min):
                samples.append((lon, lat, half + uncertain))
            ring = _swath_ring(samples) if len(samples) > 1 else _circle_ring(
                *self._centre_at(now + t_min), self._damage_half_width(now + t_min) + uncertain,
            )
            outlines.append({
                "t_min": t_min,
                "type": "Feature",
                "id": f"fc_{t_min}",
                "properties": {"kind": "tornado", "t_min": t_min, "zone": "predicted"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
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
        speed = max(self._storm_speed_m_per_min(), 1.0)
        covers = float(self.minutes + ROUTE_WINDOW_MIN + LOOKAHEAD_MIN)
        covers = min(covers, self.minutes + MAX_PATH_M / speed)
        # Bounding box: meander + flank + peak damage + pad.
        pad = CORE_R_PEAK + DEBRIS_PAD_M + CURVE_M_PER_KM * 40 + SINE_AMP_M + 2500
        end_lon, end_lat = self._centre_at(covers)
        corners = [
            _offset_ll(self.lon, self.lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ] + [
            _offset_ll(end_lon, end_lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ]
        # Also cover mid-track meander extrema.
        for t in (covers * 0.33, covers * 0.66):
            lon, lat = self._centre_at(t)
            corners.extend(_offset_ll(lon, lat, de, dn) for de, dn in ((-pad, 0), (pad, 0), (0, -pad), (0, pad)))
        if self.domain_bbox is not None:
            d = self.domain_bbox
            corners.extend([[d[0], d[1]], [d[2], d[1]], [d[0], d[3]], [d[2], d[3]]])
        xs, ys = [], []
        for lon, lat in corners:
            x, y = TO_UTM.transform(lon, lat)
            xs.append(x)
            ys.append(y)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        x0 = math.floor(min_x / CELL_M) * CELL_M
        y0 = math.ceil(max_y / CELL_M) * CELL_M
        ncols = max(1, int(math.ceil((max_x - x0) / CELL_M)))
        nrows = max(1, int(math.ceil((y0 - min_y) / CELL_M)))
        if nrows * ncols > 500_000:
            ncols = min(ncols, 700)
            nrows = min(nrows, 700)

        arrival = np.full(nrows * ncols, np.inf, dtype=np.float64)
        in_domain = np.ones(nrows * ncols, dtype=bool)

        step = max(0.2, (CELL_M * 0.45) / speed)
        t = 0.0
        while t <= covers + 1e-9:
            clon, clat = self._centre_at(t)
            cx, cy = TO_UTM.transform(clon, clat)
            rad = self._damage_half_width(t) + CELL_M * 0.75
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
                    if (cell_x - cx) ** 2 + (cell_y - cy) ** 2 <= rad_sq and t < arrival[flat]:
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
