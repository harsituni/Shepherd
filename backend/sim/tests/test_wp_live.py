"""Live forecast for WildfireSim: memory reuse, nearby-cache fallback, no key leaks.

OpenWeather is mocked with saved fixture responses; nothing touches the network.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import responses

from backend.sim.weatherpipe import live, openweather, sources
from backend.sim.weatherpipe.live import WeatherUnavailable, live_weather

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)  # matches the fixture responses
KEY = "sk-test-not-a-real-key-123"
FIRE = (53.535, -113.663)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setattr(sources, "REPO_ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(live, "_memory", {})


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


def mock_owm(forecast_status=200):
    for endpoint, name, status in (("forecast-3h", "owm_forecast_3h.json", forecast_status),
                                   ("current", "owm_current.json", 200)):
        base, _ = openweather.ENDPOINTS[endpoint]
        responses.add(responses.GET, base, json=json.loads((FIXTURES / name).read_text()), status=status)


@responses.activate
def test_live_forecast_becomes_an_hourly_series(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    weather, source = live_weather(*FIRE, T0, cache_dir=cache_dir)

    assert [w["t_min"] for w in weather] == list(range(0, 601, 60))  # 20:00 to the last slot at 06:00
    assert source["provider"] == "openweather" and source["endpoint"] == "forecast-3h"
    params = responses.calls[0].request.params
    assert (float(params["lat"]), float(params["lon"])) == (53.53, -113.66)  # rounded to ~1 km
    assert all(KEY not in p.read_text() for p in cache_dir.iterdir())


@responses.activate
def test_same_spot_within_ten_minutes_reuses_the_fetch(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    first, _ = live_weather(*FIRE, T0, cache_dir=cache_dir)
    calls = len(responses.calls)
    again, source = live_weather(FIRE[0] - 0.003, FIRE[1], T0, cache_dir=cache_dir)  # same 0.01° cell
    assert len(responses.calls) == calls and again == first and source["reused_from_memory"]

    clock = live.time.monotonic() + live.MEMORY_TTL_S + 1
    monkeypatch.setattr(live.time, "monotonic", lambda: clock)
    mock_owm()
    live_weather(*FIRE, T0, cache_dir=cache_dir)
    assert len(responses.calls) > calls


@responses.activate
def test_no_key_falls_back_to_a_nearby_cached_forecast(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    cached, _ = live_weather(53.50, -113.565, T0, cache_dir=cache_dir)  # ~7 km away
    monkeypatch.delenv("OPENWEATHER_API_KEY")
    responses.reset()

    weather, source = live_weather(*FIRE, T0, cache_dir=cache_dir)
    assert weather == cached and len(responses.calls) == 0
    assert "OPENWEATHER_API_KEY" in source["fallback_reason"]
    assert (source["lat"], source["lon"]) == (53.5, -113.56)


@responses.activate
def test_far_away_cache_is_not_used(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    live_weather(51.05, -114.07, T0, cache_dir=cache_dir)  # Calgary
    monkeypatch.delenv("OPENWEATHER_API_KEY")
    with pytest.raises(WeatherUnavailable, match="no usable cached forecast"):
        live_weather(*FIRE, T0, cache_dir=cache_dir)


@responses.activate
def test_stale_cache_that_misses_the_start_is_unavailable(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    live_weather(*FIRE, T0, cache_dir=cache_dir)
    monkeypatch.delenv("OPENWEATHER_API_KEY")
    monkeypatch.setattr(live, "_memory", {})
    with pytest.raises(WeatherUnavailable, match="does not cover"):
        live_weather(*FIRE, T0 + timedelta(days=7), cache_dir=cache_dir)


@responses.activate
def test_rejected_key_falls_back_without_leaking_it(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm(forecast_status=401)
    with pytest.raises(WeatherUnavailable) as err:
        live_weather(*FIRE, T0, cache_dir=cache_dir)
    assert "HTTP 401" in str(err.value) and KEY not in str(err.value)
    assert len(responses.calls) == 1  # no retries on a live start


@responses.activate
def test_requests_errors_never_carry_the_key(monkeypatch, cache_dir):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    base, _ = openweather.ENDPOINTS["forecast-3h"]
    # requests puts the full URL in messages like this one, key included.
    responses.add(responses.GET, base, body=requests.exceptions.InvalidURL(f"{base}?appid={KEY}"))
    with pytest.raises(WeatherUnavailable) as err:
        live_weather(*FIRE, T0, cache_dir=cache_dir)
    assert "InvalidURL" in str(err.value) and KEY not in str(err.value)
