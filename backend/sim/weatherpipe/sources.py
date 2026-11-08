"""One entry point for every weather source: live OpenWeather, cached response, canned series.

The API key comes from the OPENWEATHER_API_KEY environment variable, or failing
that from the repo-root .env file (gitignored; see .env.example).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.sim.weatherpipe import cache, openweather
from backend.sim.weatherpipe.conventions import iso_z, require_utc
from backend.sim.weatherpipe.obs import WeatherObs, make_obs, merge_obs

API_KEY_ENV = "OPENWEATHER_API_KEY"
SIM_DIR = Path(__file__).resolve().parents[1]
REPO_ENV_FILE = SIM_DIR.parents[1] / ".env"
DEFAULT_CACHE_DIR = SIM_DIR / "weather_cache"
POINT_FORECAST_NOTE = (
    "single-point forecast at the bbox centroid, applied uniformly to the whole grid"
)


def api_key(env_file: Path | None = None) -> str | None:
    """OPENWEATHER_API_KEY from the environment, else from KEY=value lines in .env."""
    if os.environ.get(API_KEY_ENV):
        return os.environ[API_KEY_ENV]
    env_file = env_file or REPO_ENV_FILE
    if not env_file.is_file():
        return None
    for line in env_file.read_text().splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == API_KEY_ENV:
            return value.strip().strip("'\"") or None
    return None


def fetch_weather(lat: float, lon: float, source: str = "openweather:forecast-3h", *,
                  t0: datetime | None = None, cache_dir=DEFAULT_CACHE_DIR,
                  session=None, **http) -> tuple[list[WeatherObs], dict]:
    """Returns normalised observations + a weather_source dict. source ∈
    {"openweather:forecast-3h", "openweather:onecall-hourly", "cache:<path>", "cache:latest",
    "canned:<path>"}.

    cache:latest replays the newest cached forecast for this lat/lon in cache_dir.
    canned:<path> needs t0, because a canned series is in Contract A form (t_min after t0).
    http: optional timeout_s / retries for the OpenWeather requests.
    """
    kind, _, arg = source.partition(":")
    if kind == "openweather":
        return _live(lat, lon, arg, cache_dir, session, http)
    if kind == "cache":
        if arg == "latest":
            return _cached(cache.latest_forecast(cache_dir, lat, lon, openweather.FORECAST_ENDPOINTS))
        return _cached(Path(arg))
    if kind == "canned":
        if t0 is None:
            raise ValueError("canned weather needs t0 to anchor its t_min values")
        return _canned(Path(arg), require_utc(t0))
    raise ValueError(f"unknown weather source {source!r}")


def _live(lat, lon, endpoint, cache_dir, session, http):
    if endpoint not in openweather.FORECAST_ENDPOINTS:
        raise ValueError(f"unknown OpenWeather endpoint {endpoint!r}, expected {openweather.FORECAST_ENDPOINTS}")
    key = api_key()
    if not key:
        raise RuntimeError(
            f"{API_KEY_ENV} is not set (environment or {REPO_ENV_FILE}); "
            "use --source cache:latest or a canned: source offline"
        )
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0)
    paths = {}
    obs = {}
    for name in (endpoint, "current"):
        raw = openweather.fetch_raw(name, lat, lon, key, session, **http)
        paths[name] = cache.save_raw(
            cache_dir, openweather.PROVIDER, name, lat, lon, fetched_at,
            openweather.public_url(name, lat, lon), raw, secret=key,
        )
        obs[name] = openweather.PARSERS[name](raw)
    return merge_obs(obs["current"], obs[endpoint]), _source_info(
        endpoint, fetched_at, lat, lon, cache_path=str(paths[endpoint]))


def _cached(path):
    envelope = cache.load_raw(path)
    endpoint = envelope["endpoint"]
    forecast = openweather.PARSERS[endpoint](envelope["response"])
    anchor_path = cache.sibling_path(path, "current")
    anchor = []
    if endpoint != "current" and anchor_path.exists():
        anchor = openweather.obs_from_current(cache.load_raw(anchor_path)["response"])
    fetched_at = datetime.fromisoformat(envelope["fetched_at"])
    return merge_obs(anchor, forecast), _source_info(
        endpoint, fetched_at, envelope["lat"], envelope["lon"], cache_path=str(path))


def _canned(path, t0):
    data = json.loads(path.read_text())
    entries = data["weather"] if isinstance(data, dict) else data
    obs = [
        make_obs(
            time_utc=t0 + timedelta(minutes=e["t_min"]),
            wind_speed_ms=e["wind_speed_ms"],
            wind_dir_deg=e["wind_dir_deg"],
            temp_c=e["temp_c"],
            rh_pct=e["rh_pct"],
            precip_mm_per_h=e["precip_mm"],
            gust_ms=e.get("gust_ms"),
        )
        for e in entries
    ]
    return merge_obs([], obs), {"provider": "canned", "path": str(path), "note": POINT_FORECAST_NOTE}


def _source_info(endpoint, fetched_at, lat, lon, **extra):
    return {
        "provider": openweather.PROVIDER,
        "endpoint": endpoint,
        "fetched_at": iso_z(fetched_at),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "note": POINT_FORECAST_NOTE,
        **extra,
    }
