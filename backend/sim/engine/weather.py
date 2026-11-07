"""Forecast weather → per-minute fire spread lookup table.

This is the only module that converts wind units (contract m/s → FBP km/h) or
turns the meteorological "from" direction into the bearing fire spreads toward.

Wind is interpolated as (u, v) vector components between the bracketing hourly
entries, so 350° → 10° passes through 0° rather than 180°. Before the first entry
or after the last, the nearest entry is held constant.

Bearings are grid bearings: grid north = UTM 12N north. UTM grid convergence
(≤ ~2° here) is ignored.
"""

import bisect
import math
from dataclasses import dataclass

import numpy as np

from backend.sim.engine import fbp

KMH_PER_MS = 3.6


def ms_to_kmh(speed_ms):
    return speed_ms * KMH_PER_MS


def spread_bearing(wind_dir_deg):
    """Bearing fire spreads toward, from the direction the wind blows from."""
    return (wind_dir_deg + 180) % 360


def wind_to_uv(speed, from_deg):
    """Wind vector (u east, v north) the air moves along."""
    rad = math.radians(from_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)


def uv_to_wind(u, v):
    """(speed, from_deg) for a wind vector; inverse of wind_to_uv."""
    return math.hypot(u, v), math.degrees(math.atan2(-u, -v)) % 360


def interpolate_wind(weather, t):
    """(wind_speed_ms, wind_dir_deg) at sim minute t.

    weather: entries sorted by t_min, each with t_min, wind_speed_ms, wind_dir_deg.
    """
    times = [w.t_min for w in weather]
    if t <= times[0]:
        return weather[0].wind_speed_ms, weather[0].wind_dir_deg
    if t >= times[-1]:
        return weather[-1].wind_speed_ms, weather[-1].wind_dir_deg
    hi = bisect.bisect_right(times, t)
    before, after = weather[hi - 1], weather[hi]
    frac = (t - before.t_min) / (after.t_min - before.t_min)
    u0, v0 = wind_to_uv(before.wind_speed_ms, before.wind_dir_deg)
    u1, v1 = wind_to_uv(after.wind_speed_ms, after.wind_dir_deg)
    return uv_to_wind(u0 + (u1 - u0) * frac, v0 + (v1 - v0) * frac)


@dataclass(frozen=True)
class WeatherTable:
    """Wind and FBP spread rates for every whole sim minute 0..horizon (index = t_min)."""

    wind_speed_ms: np.ndarray
    wind_dir_deg: np.ndarray
    ros: np.ndarray
    bros: np.ndarray
    fros: np.ndarray
    lb: np.ndarray
    spread_bearing_deg: np.ndarray

    def __len__(self):
        return len(self.ros)

    def index(self, t):
        """Table row for sim time t (minutes): the whole minute it falls in."""
        return min(int(t), len(self) - 1)


def build_weather_table(weather, fuel, horizon_min) -> WeatherTable:
    """Precompute spread rates per minute so the spread loop never calls exp.

    fuel: anything with fuel_type, pc, ffmc and bui attributes.
    """
    winds = [interpolate_wind(weather, t) for t in range(horizon_min + 1)]
    speed_ms = np.array([s for s, _ in winds])
    dir_deg = np.array([d for _, d in winds])
    rates = fbp.spread_rates(fuel.fuel_type, fuel.pc, fuel.ffmc, fuel.bui, ms_to_kmh(speed_ms))
    return WeatherTable(
        wind_speed_ms=speed_ms,
        wind_dir_deg=dir_deg,
        ros=rates.ros,
        bros=rates.bros,
        fros=rates.fros,
        lb=rates.lb,
        spread_bearing_deg=spread_bearing(dir_deg),
    )
