"""The normalised weather record every source is converted into."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from backend.sim.weatherpipe.conventions import (
    RH_RANGE_PCT,
    SPEED_RANGE_MS,
    TEMP_RANGE_C,
    require_utc,
)


class WeatherRangeError(ValueError):
    """A weather value is outside its physical range. Never clipped silently."""


@dataclass(frozen=True)
class WeatherObs:
    time_utc: datetime        # tz-aware UTC
    wind_speed_ms: float
    wind_dir_deg: float       # meteorological from-direction, [0, 360)
    temp_c: float
    rh_pct: float
    precip_mm_per_h: float    # rain["3h"] / 3, rain["1h"] as-is, missing → 0
    gust_ms: float | None = None


def _check(name, value, lo, hi, when):
    if not math.isfinite(value) or not (lo <= value <= hi):
        raise WeatherRangeError(f"{name}={value} out of range [{lo}, {hi}] at {when}")


def make_obs(time_utc, wind_speed_ms, wind_dir_deg, temp_c, rh_pct, precip_mm_per_h, gust_ms=None) -> WeatherObs:
    """Validated WeatherObs; direction 360 is normalised to 0."""
    when = require_utc(time_utc, "time_utc")
    _check("wind_speed_ms", wind_speed_ms, *SPEED_RANGE_MS, when)
    _check("wind_dir_deg", wind_dir_deg, 0, 360, when)
    _check("temp_c", temp_c, *TEMP_RANGE_C, when)
    _check("rh_pct", rh_pct, *RH_RANGE_PCT, when)
    _check("precip_mm_per_h", precip_mm_per_h, 0, float("inf"), when)
    if gust_ms is not None:
        _check("gust_ms", gust_ms, *SPEED_RANGE_MS, when)
    return WeatherObs(
        time_utc=when,
        wind_speed_ms=float(wind_speed_ms),
        wind_dir_deg=float(wind_dir_deg) % 360,
        temp_c=float(temp_c),
        rh_pct=float(rh_pct),
        precip_mm_per_h=float(precip_mm_per_h),
        gust_ms=None if gust_ms is None else float(gust_ms),
    )


def merge_obs(anchor: list[WeatherObs], forecast: list[WeatherObs]) -> list[WeatherObs]:
    """Sorted by time, one record per timestamp; forecast wins over the anchor."""
    by_time = {o.time_utc: o for o in anchor}
    by_time.update({o.time_utc: o for o in forecast})
    return [by_time[t] for t in sorted(by_time)]
