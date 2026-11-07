"""OpenWeather HTTP adapters and raw → WeatherObs mapping.

The only module that knows OpenWeather URLs and field names (checked against
the docs at openweathermap.org/forecast5, /current and /api/one-call-3).
Every request uses units=metric, so wind arrives in m/s and temperature in °C.

The API key is passed only as a request parameter. It is never logged, put in
an error message, or returned in a URL.
"""

import logging
import time
from datetime import datetime, timezone

import requests

from backend.sim.weatherpipe.conventions import HTTP_BACKOFF_S, HTTP_RETRIES, HTTP_TIMEOUT_S
from backend.sim.weatherpipe.obs import WeatherObs, make_obs

log = logging.getLogger(__name__)

PROVIDER = "openweather"
ENDPOINTS = {
    "forecast-3h": ("https://api.openweathermap.org/data/2.5/forecast", {}),
    "onecall-hourly": (
        "https://api.openweathermap.org/data/3.0/onecall",
        {"exclude": "minutely,daily,alerts"},
    ),
    "current": ("https://api.openweathermap.org/data/2.5/weather", {}),
}
FORECAST_ENDPOINTS = ("forecast-3h", "onecall-hourly")


class OpenWeatherError(RuntimeError):
    """A request failed; names the endpoint and HTTP status, never the key."""


def public_url(endpoint, lat, lon) -> str:
    """The request URL without the API key, safe to store."""
    base, extra = ENDPOINTS[endpoint]
    params = {"lat": lat, "lon": lon, "units": "metric", **extra}
    return requests.Request("GET", base, params=params).prepare().url


def fetch_raw(endpoint, lat, lon, api_key, session=None) -> dict:
    """GET one endpoint. Retries 5xx and connection errors; never retries 4xx."""
    base, extra = ENDPOINTS[endpoint]
    params = {"lat": lat, "lon": lon, "units": "metric", **extra, "appid": api_key}
    http = session or requests
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = http.get(base, params=params, timeout=HTTP_TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = type(exc).__name__
            status = None
        else:
            if resp.status_code < 400:
                log.info("openweather %s: HTTP %s", endpoint, resp.status_code)
                try:
                    data = resp.json()
                except ValueError:
                    raise OpenWeatherError(f"openweather {endpoint}: invalid JSON response") from None
                if not isinstance(data, dict):
                    raise OpenWeatherError(f"openweather {endpoint}: expected a JSON object")
                return data
            reason = f"HTTP {resp.status_code}"
            status = resp.status_code
            if status < 500:
                raise OpenWeatherError(f"openweather {endpoint} failed: {reason} (not retried)")
        if attempt < HTTP_RETRIES:
            log.warning("openweather %s: %s, retrying", endpoint, reason)
            time.sleep(HTTP_BACKOFF_S[attempt])
    raise OpenWeatherError(
        f"openweather {endpoint} failed after {HTTP_RETRIES + 1} attempts: {reason}"
    )


def _utc(unix_s) -> datetime:
    return datetime.fromtimestamp(unix_s, tz=timezone.utc)


def obs_from_forecast_3h(raw) -> list[WeatherObs]:
    return [
        make_obs(
            time_utc=_utc(item["dt"]),
            wind_speed_ms=item["wind"]["speed"],
            wind_dir_deg=item["wind"]["deg"],
            temp_c=item["main"]["temp"],
            rh_pct=item["main"]["humidity"],
            precip_mm_per_h=item.get("rain", {}).get("3h", 0.0) / 3,
            gust_ms=item["wind"].get("gust"),
        )
        for item in raw["list"]
    ]


def obs_from_onecall_hourly(raw) -> list[WeatherObs]:
    return [
        make_obs(
            time_utc=_utc(item["dt"]),
            wind_speed_ms=item["wind_speed"],
            wind_dir_deg=item["wind_deg"],
            temp_c=item["temp"],
            rh_pct=item["humidity"],
            precip_mm_per_h=item.get("rain", {}).get("1h", 0.0),
            gust_ms=item.get("wind_gust"),
        )
        for item in raw["hourly"]
    ]


def obs_from_current(raw) -> list[WeatherObs]:
    return [
        make_obs(
            time_utc=_utc(raw["dt"]),
            wind_speed_ms=raw["wind"]["speed"],
            wind_dir_deg=raw["wind"]["deg"],
            temp_c=raw["main"]["temp"],
            rh_pct=raw["main"]["humidity"],
            precip_mm_per_h=raw.get("rain", {}).get("1h", 0.0),
            gust_ms=raw["wind"].get("gust"),
        )
    ]


PARSERS = {
    "forecast-3h": obs_from_forecast_3h,
    "onecall-hourly": obs_from_onecall_hourly,
    "current": obs_from_current,
}
