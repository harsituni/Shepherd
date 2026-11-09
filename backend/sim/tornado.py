"""BETA: supercell tornado for demos — EF category, track, life cycle, damage swath.

Tornado simulation is a beta feature; the wildfire sim is the supported hazard.
Same public surface as WildfireSim (step / features / forecast / set_wind /
oracle) so SimController and routing can treat it as another hazard.

Physics (simplified but grounded):
    • Peak intensity is an Enhanced Fujita (EF0–EF5) rating chosen at start.
    • The *storm* translates roughly with the steering wind (FROM + 180°).
    • The tornado sits on the right-rear flank (N. Hemisphere supercell habit)
      and meanders: slow cyclonic curve, along-track sine, and a small wobble.
    • Intensity follows a life cycle: organizes → mature → rope-out. Current EF
      and path width scale with that (narrow → violent corridor → thin again).
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
# Meander: cyclonic curve + along-track oscillation.
CURVE_M_PER_KM = 55
SINE_AMP_M = 380
SINE_WAVELENGTH_M = 6500
WOBBLE_AMP_M = 90
DEBRIS_PAD_M = 220
SCAR_PAD_M = 40

# Enhanced Fujita scale — mid-band estimated winds and typical damage widths.
# Winds are the *rotational* estimate at the funnel, not storm translation.
# core_peak_m is half-width of the damage path at mature peak (demo-scale; real
# EF5 corridors can run wider, but that swallows the whole city on this map).
EF_TABLE = {
    0: {"label": "EF0", "wind_mph": 75,  "wind_kmh": 121, "core_peak_m": 45,  "desc": "Light damage"},
    1: {"label": "EF1", "wind_mph": 98,  "wind_kmh": 158, "core_peak_m": 80,  "desc": "Moderate damage"},
    2: {"label": "EF2", "wind_mph": 123, "wind_kmh": 198, "core_peak_m": 130, "desc": "Considerable damage"},
    3: {"label": "EF3", "wind_mph": 150, "wind_kmh": 241, "core_peak_m": 190, "desc": "Severe damage"},
    4: {"label": "EF4", "wind_mph": 183, "wind_kmh": 295, "core_peak_m": 260, "desc": "Devastating damage"},
    5: {"label": "EF5", "wind_mph": 220, "wind_kmh": 354, "core_peak_m": 340, "desc": "Incredible damage"},
}
CORE_R_ORG_FRAC = 0.22
CORE_R_ROPE_FRAC = 0.12

_VERSIONS = itertools.count(1)


def _clamp_wind(wind_kmh: float, wind_from_deg: float) -> tuple[float, float]:
    return max(0.0, float(wind_kmh)), float(wind_from_deg) % 360.0


def _clamp_ef(value) -> int:
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return 2


def ef_from_steering_wind(wind_kmh: float) -> int:
    """Default peak EF when the dashboard doesn't pick a category."""
    w = max(0.0, float(wind_kmh))
    if w < 12:
        return 0
    if w < 22:
        return 1
    if w < 35:
        return 2
    if w < 48:
        return 3
    if w < 58:
        return 4
    return 5


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

    def cap(lon, lat, half, dx, dy, outward_sign):
        length = math.hypot(dx, dy) or 1.0
        ang0 = math.atan2(dy / length, dx / length)
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
                 ef_rating: Optional[int] = None, weather=None, t0=None,
                 weather_source: Optional[dict] = None,
                 domain_bbox: Optional[list] = None):
        del fuel_dryness, weather, t0
        self.lat = float(lat)
        self.lon = float(lon)
        self.wind_kmh, self.wind_from_deg = _clamp_wind(wind_kmh, wind_from_deg)
        self.ef_peak = (
            _clamp_ef(ef_rating) if ef_rating is not None else ef_from_steering_wind(self.wind_kmh)
        )
        self.weather_source = dict(weather_source or {"provider": "dashboard"})
        self.domain_bbox = list(domain_bbox) if domain_bbox else None
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
        need = self.minutes + ROUTE_WINDOW_MIN + LOOKAHEAD_MIN
        if self._oracle is None or self._oracle.covers_until_sim_min < need:
            self._rebuild_oracle()
        else:
            # Keep the painted track; advance the declared coverage window with the clock.
            self._oracle = ForecastOracle(
                version=self._oracle.version, run_id=self._oracle.run_id, band="p50",
                sim_time=self.minutes, covers_until_sim_min=float(need),
                wind_kmh=self.wind_kmh, wind_from_deg=self.wind_from_deg,
                x0=self._oracle.x0, y0=self._oracle.y0, cell_m=self._oracle.cell_m,
                nrows=self._oracle.nrows, ncols=self._oracle.ncols,
                arrival=self._oracle.arrival, in_domain=self._oracle.in_domain,
                outlines=self._oracle.outlines,
            )

    def _storm_speed_kmh(self) -> float:
        return min(STORM_SPEED_CAP_KMH, max(STORM_SPEED_FLOOR_KMH, self.wind_kmh * STORM_SPEED_FRAC))

    def _storm_speed_m_per_min(self) -> float:
        return (self._storm_speed_kmh() * 1000.0) / 60.0

    def _peak_core_m(self) -> float:
        return float(EF_TABLE[self.ef_peak]["core_peak_m"])

    def _intensity(self, t_min: float) -> float:
        """0..1 life-cycle intensity (organize → mature → dissipate)."""
        t = max(0.0, t_min)
        if t <= ORGANIZE_MIN:
            return 0.15 + 0.55 * (t / ORGANIZE_MIN)
        if t <= MATURE_MIN:
            u = (t - ORGANIZE_MIN) / max(1.0, MATURE_MIN - ORGANIZE_MIN)
            return 0.7 + 0.3 * math.sin(u * math.pi)
        if t <= DISSIPATE_MIN:
            u = (t - MATURE_MIN) / max(1.0, DISSIPATE_MIN - MATURE_MIN)
            return max(0.08, 1.0 - 0.92 * u)
        return 0.08

    def _phase_name(self, t_min: float) -> str:
        t = max(0.0, t_min)
        if t <= ORGANIZE_MIN:
            return "organizing"
        if t <= MATURE_MIN:
            return "mature"
        if t <= DISSIPATE_MIN:
            return "dissipating"
        return "remnant"

    def _ef_at(self, t_min: float) -> int:
        """Current EF from peak rating × life-cycle intensity."""
        inten = self._intensity(t_min)
        if inten < 0.2:
            return 0
        # Scale toward peak; floor at 0 during rope-out.
        scaled = self.ef_peak * inten
        return max(0, min(self.ef_peak, int(round(scaled))))

    def _core_radius(self, t_min: float) -> float:
        peak = self._peak_core_m()
        inten = self._intensity(t_min)
        rope = peak * CORE_R_ROPE_FRAC
        org = peak * CORE_R_ORG_FRAC
        if inten < 0.7:
            return rope + (peak * 0.55 - rope) * (inten / 0.7)
        return org + (peak - org) * ((inten - 0.5) / 0.5)

    def _damage_half_width(self, t_min: float) -> float:
        return self._core_radius(t_min) + SCAR_PAD_M

    def _heading(self) -> float:
        return _toward_rad(self.wind_from_deg)

    def _centre_at(self, t_min: float) -> tuple[float, float]:
        """Ground circulation centre (lon, lat) at sim minute t_min."""
        t = max(0.0, t_min)
        heading = self._heading()
        along = self._storm_speed_m_per_min() * t
        east = along * math.sin(heading)
        north = along * math.cos(heading)
        right = heading + math.pi / 2
        east += FLANK_RIGHT_M * math.sin(right) - FLANK_BACK_M * math.sin(heading)
        north += FLANK_RIGHT_M * math.cos(right) - FLANK_BACK_M * math.cos(heading)
        east += (along / 1000.0) * CURVE_M_PER_KM * math.sin(right)
        north += (along / 1000.0) * CURVE_M_PER_KM * math.cos(right)
        phase = self._phase + along * (2 * math.pi / SINE_WAVELENGTH_M)
        east += SINE_AMP_M * math.sin(phase) * math.sin(right)
        north += SINE_AMP_M * math.sin(phase) * math.cos(right)
        w = self._phase * 3.7 + along * 0.012
        east += WOBBLE_AMP_M * math.sin(w) * math.sin(heading)
        north += WOBBLE_AMP_M * math.cos(w * 1.3) * math.cos(heading)
        lon, lat = _offset_ll(self.lon, self.lat, east, north)
        return lon, lat

    def _track_km(self, t_min: float) -> float:
        return round(self._storm_speed_m_per_min() * max(0.0, t_min) / 1000.0, 1)

    def stats(self, t_min: Optional[float] = None) -> dict:
        """Live tornado readout for /sim/state and hazard properties."""
        t = float(self.minutes if t_min is None else t_min)
        ef = self._ef_at(t)
        band = EF_TABLE[ef]
        peak = EF_TABLE[self.ef_peak]
        width = round(self._core_radius(t) * 2)
        return {
            "ef_rating": ef,
            "ef_label": band["label"],
            "ef_peak": self.ef_peak,
            "ef_peak_label": peak["label"],
            "ef_desc": band["desc"],
            "phase": self._phase_name(t),
            "intensity": round(self._intensity(t), 2),
            "wind_est_mph": int(band["wind_mph"]),
            "wind_est_kmh": int(band["wind_kmh"]),
            "path_width_m": width,
            "forward_speed_kmh": round(self._storm_speed_kmh(), 1),
            "track_km": self._track_km(t),
            "heading_deg": round((self.wind_from_deg + 180.0) % 360.0, 1),
        }

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

    def _core_ring(self, t_min: float) -> list[list[float]]:
        """The funnel on the ground at t_min: an ellipse along the track."""
        lon, lat = self._centre_at(t_min)
        core_r = self._core_radius(t_min)
        return _ellipse_ring(lon, lat, core_r * 1.25, core_r * 0.85, self._heading())

    def features(self) -> list[dict]:
        now = float(self.minutes)
        lon, lat = self._centre_at(now)
        core_r = self._core_radius(now)
        stats = self.stats(now)
        features = []
        if now > 1.0:
            scar = _swath_ring(self._track_samples(0.0, now))
            if scar:
                features.append({
                    "type": "Feature",
                    "id": "hz_tornado_scar",
                    "properties": {
                        "kind": "tornado", "zone": "buffer", "source": "sim", "role": "damage_path",
                        "ef_peak": stats["ef_peak"], "track_km": stats["track_km"],
                    },
                    "geometry": {"type": "Polygon", "coordinates": [scar]},
                })
        features.append({
            "type": "Feature",
            "id": "hz_tornado_debris",
            "properties": {
                "kind": "tornado", "zone": "buffer", "source": "sim", "role": "debris",
                "ef_rating": stats["ef_rating"],
            },
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
                **stats,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [self._core_ring(now)],
            },
        })
        return features

    def forecast(self, horizon_min: int = HORIZON_MIN) -> list[dict]:
        """Predicted damage-corridor outlines (uncertainty grows with lead time)."""
        now = float(self.minutes)
        outlines = []
        for t_min in range(FORECAST_STEP_MIN, int(horizon_min) + 1, FORECAST_STEP_MIN):
            # Forecast corridor widens slowly with lead time (not a city-sized cone).
            uncertain = 25.0 * (t_min / 15.0)
            samples = []
            for lon, lat, half in self._track_samples(now, now + t_min):
                samples.append((lon, lat, half + uncertain))
            ring = _swath_ring(samples) if len(samples) > 1 else _circle_ring(
                *self._centre_at(now + t_min), self._damage_half_width(now + t_min) + uncertain,
            )
            future = self.stats(now + t_min)
            outlines.append({
                "t_min": t_min,
                "type": "Feature",
                "id": f"fc_{t_min}",
                "properties": {
                    "kind": "tornado", "t_min": t_min, "zone": "predicted",
                    "ef_rating": future["ef_rating"], "ef_label": future["ef_label"],
                    "phase": future["phase"],
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
        return outlines

    def oracle(self) -> ForecastOracle:
        if self._oracle is None:
            self._rebuild_oracle()
        return self._oracle

    def _rebuild_oracle(self) -> None:
        speed = max(self._storm_speed_m_per_min(), 1.0)
        # Routing needs ~now + 240 min of declared coverage or every journey goes
        # indeterminate. Paint only a finite track ahead; cells past the funnel
        # stay +inf (= not reached) inside that complete window.
        covers = float(self.minutes + ROUTE_WINDOW_MIN + LOOKAHEAD_MIN)
        paint_until = min(covers, float(self.minutes) + MAX_PATH_M / speed)
        pad = self._peak_core_m() + DEBRIS_PAD_M + CURVE_M_PER_KM * 40 + SINE_AMP_M + 2500
        end_lon, end_lat = self._centre_at(paint_until)
        corners = [
            _offset_ll(self.lon, self.lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ] + [
            _offset_ll(end_lon, end_lat, de, dn)
            for de, dn in ((-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad))
        ]
        for t in (paint_until * 0.33, paint_until * 0.66):
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
        while t <= paint_until + 1e-9:
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
        # The core outline at every minute: what the map draws as the funnel.
        outlines = np.array([self._core_ring(float(m)) for m in range(int(covers) + 1)])
        outlines.flags.writeable = False
        self._oracle = ForecastOracle(
            version=self._version, run_id=f"tornado-{self._version}", band="p50",
            sim_time=self.minutes, covers_until_sim_min=covers,
            wind_kmh=self.wind_kmh, wind_from_deg=self.wind_from_deg,
            x0=float(x0), y0=float(y0), cell_m=float(CELL_M),
            nrows=int(nrows), ncols=int(ncols),
            arrival=arrival, in_domain=in_domain, outlines=outlines,
        )
