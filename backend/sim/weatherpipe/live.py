"""Forecast weather for the live WildfireSim, called once per /sim/start.

Order of preference, so the demo never dies:
    1. A fetch for the same spot in the last 10 minutes (kept in memory).
    2. Live OpenWeather 3-hourly forecast + current conditions (short timeout, no retries).
    3. The newest cached forecast fetched within 25 km (backend/sim/weather_cache).
Otherwise WeatherUnavailable, and the caller falls back to the dashboard's wind.

The fire's location is rounded to 0.01 degrees (about 1 km) before fetching, so
starts in the same 0.01-degree cell share a fetch. The forecast is a single point
applied to the whole fire domain.
"""

import logging
import math
import time
from datetime import datetime

from backend.sim.weatherpipe import cache, openweather
from backend.sim.weatherpipe.conventions import SERIES_STEP_MIN, require_utc
from backend.sim.weatherpipe.resample import build_weather_series, coverage_metadata
from backend.sim.weatherpipe.sources import DEFAULT_CACHE_DIR, fetch_weather

log = logging.getLogger(__name__)

SOURCE = "openweather:forecast-3h"
LIVE_TIMEOUT_S = 4
LIVE_RETRIES = 0
MEMORY_TTL_S = 600
NEARBY_CACHE_KM = 25

_memory: dict[tuple[float, float], tuple[float, list, dict]] = {}


class WeatherUnavailable(RuntimeError):
    """Neither a live nor a cached forecast covers the start time."""


def live_weather(lat: float, lon: float, t0: datetime, *, cache_dir=DEFAULT_CACHE_DIR,
                 session=None) -> tuple[list[dict], dict]:
    """Hourly Contract A weather from t0 (t_min 0, 60, ...) as far as the forecast reaches,
    plus a weather_source dict saying where it came from."""
    t0 = require_utc(t0)
    spot = (round(lat, 2), round(lon, 2))
    hit = _memory.get(spot)
    if hit and time.monotonic() - hit[0] < MEMORY_TTL_S:
        obs, source = hit[1], {**hit[2], "reused_from_memory": True}
    else:
        try:
            obs, source = fetch_weather(*spot, SOURCE, cache_dir=cache_dir, session=session,
                                        timeout_s=LIVE_TIMEOUT_S, retries=LIVE_RETRIES)
            _memory[spot] = (time.monotonic(), obs, source)
        except Exception as live_error:  # any failure here must not stop the fire starting
            obs, source = _cached_near(spot, cache_dir, live_error)
    try:
        weather = build_weather_series(obs, t0, _reach_min(obs, t0))
    except ValueError as exc:
        raise WeatherUnavailable(f"forecast from {source.get('fetched_at')} does not cover {t0}: {exc}") from None
    return weather, {**source, **coverage_metadata(obs, t0, weather[-1]["t_min"])}


def _cached_near(spot, cache_dir, live_error):
    reason = f"live fetch failed ({type(live_error).__name__}: {live_error})"
    try:
        path = cache.latest_forecast_near(cache_dir, *spot, openweather.FORECAST_ENDPOINTS, NEARBY_CACHE_KM)
        obs, source = fetch_weather(*spot, f"cache:{path}")
    except Exception as cache_error:
        raise WeatherUnavailable(f"{reason}; no usable cached forecast ({cache_error})") from None
    log.warning("wildfire weather: %s, using cached forecast from %s", reason, source["fetched_at"])
    return obs, {**source, "fallback_reason": reason}


def _reach_min(obs, t0) -> int:
    """Whole hours from t0 to the last observation (at least one)."""
    last = max(o.time_utc for o in obs)
    hours = math.floor((last - t0).total_seconds() / 60 / SERIES_STEP_MIN)
    return max(1, hours) * SERIES_STEP_MIN
