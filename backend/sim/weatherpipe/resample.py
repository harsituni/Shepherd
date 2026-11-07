"""Resample observations to the hourly Contract A weather series.

Wind is interpolated as (u, v) vector components with the engine's own
helpers (backend.sim.engine.weather), so both sides share one convention.
Side effect worth knowing: halfway between opposite winds of equal speed
(5 m/s from 90° and 5 m/s from 270°) the vectors cancel, giving ~0 m/s.
This is an interpolation assumption; it does not prove an observed lull.
"""

import math
from datetime import datetime, timedelta

from backend.sim.engine.weather import uv_to_wind, wind_to_uv
from backend.sim.weatherpipe.conventions import MAX_HOLD_GAP_MIN, SERIES_STEP_MIN, require_utc
from backend.sim.weatherpipe.obs import WeatherObs


class CoverageError(ValueError):
    """The forecast does not cover the requested horizon."""


def _lerp(a, b, frac):
    return a + (b - a) * frac


def _entry(t_min, speed, direction, temp, rh, precip) -> dict:
    return {
        "t_min": t_min,
        "wind_speed_ms": round(speed, 1),
        "wind_dir_deg": round(direction) % 360,
        "temp_c": round(temp, 1),
        "rh_pct": round(rh, 1),
        "precip_mm": round(precip, 1),
    }


def _at(obs: list[WeatherObs], when: datetime):
    """(speed, dir, temp, rh, precip) at `when`, holding the ends for up to 3 h."""
    first, last = obs[0], obs[-1]
    max_gap = timedelta(minutes=MAX_HOLD_GAP_MIN)
    if when <= first.time_utc or when >= last.time_utc:
        nearest = first if when <= first.time_utc else last
        if abs(when - nearest.time_utc) > max_gap:
            raise CoverageError(
                f"forecast covers {first.time_utc.isoformat()} to {last.time_utc.isoformat()}, "
                f"which does not reach {when.isoformat()} (more than {MAX_HOLD_GAP_MIN} min away)"
            )
        o = nearest
        return o.wind_speed_ms, o.wind_dir_deg, o.temp_c, o.rh_pct, o.precip_mm_per_h
    hi = next(i for i, o in enumerate(obs) if o.time_utc > when)
    a, b = obs[hi - 1], obs[hi]
    if b.time_utc - a.time_utc > max_gap:
        raise CoverageError("interior weather gap exceeds 180 minutes")
    frac = (when - a.time_utc) / (b.time_utc - a.time_utc)
    ua, va = wind_to_uv(a.wind_speed_ms, a.wind_dir_deg)
    ub, vb = wind_to_uv(b.wind_speed_ms, b.wind_dir_deg)
    speed, direction = uv_to_wind(_lerp(ua, ub, frac), _lerp(va, vb, frac))
    return (
        speed,
        direction,
        _lerp(a.temp_c, b.temp_c, frac),
        _lerp(a.rh_pct, b.rh_pct, frac),
        _lerp(a.precip_mm_per_h, b.precip_mm_per_h, frac),
    )


def build_weather_series(obs: list[WeatherObs], t0: datetime, horizon_min: int) -> list[dict]:
    """Hourly Contract A weather entries, t_min = 0, 60, ... up to >= horizon_min."""
    t0 = require_utc(t0)
    if not obs:
        raise CoverageError("no weather observations")
    obs = sorted(obs, key=lambda o: o.time_utc)
    if horizon_min <= 0:
        raise ValueError("horizon_min must be positive")
    if any(a.time_utc == b.time_utc for a, b in zip(obs, obs[1:])):
        raise ValueError("duplicate weather timestamps")
    steps = math.ceil(horizon_min / SERIES_STEP_MIN)
    series = []
    for k in range(steps + 1):
        t_min = k * SERIES_STEP_MIN
        series.append(_entry(t_min, *_at(obs, t0 + timedelta(minutes=t_min))))
    return series


def coverage_metadata(obs, t0, horizon_min):
    """Retain raw observation coverage even when resampling holds the ends."""
    from backend.sim.weatherpipe.conventions import iso_z
    first, last = min(o.time_utc for o in obs), max(o.time_utc for o in obs)
    end = t0 + timedelta(minutes=math.ceil(horizon_min / 60) * 60)
    return {"observation_coverage_utc": [iso_z(first), iso_z(last)],
            "start_hold_min": max(0, (first - t0).total_seconds() / 60),
            "end_hold_min": max(0, (end - last).total_seconds() / 60),
            "resampling": "hourly vector interpolation; endpoints held at most 180 min"}
