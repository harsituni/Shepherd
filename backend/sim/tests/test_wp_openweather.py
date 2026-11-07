import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from backend.sim.weatherpipe import openweather, sources
from backend.sim.weatherpipe.cache import load_raw
from backend.sim.weatherpipe.obs import WeatherRangeError, make_obs, merge_obs
from backend.sim.weatherpipe.sources import api_key, fetch_weather

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)
KEY = "sk-test-not-a-real-key-123"
LAT, LON = 53.5, -113.565  # Edmonton demo bbox centroid


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No backoff sleeps, and never read the developer's real key or .env."""
    monkeypatch.setattr(openweather.time, "sleep", lambda s: None)
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setattr(sources, "REPO_ENV_FILE", tmp_path / "no.env")


def test_api_key_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"FIRMS_MAP_KEY=abc\n# comment\nOPENWEATHER_API_KEY='{KEY}'\n")
    assert api_key(env) == KEY
    monkeypatch.setenv("OPENWEATHER_API_KEY", "from-env")
    assert api_key(env) == "from-env"  # environment wins
    env.write_text("OPENWEATHER_API_KEY=\n")
    monkeypatch.delenv("OPENWEATHER_API_KEY")
    assert api_key(env) is None


def test_forecast_3h_mapping():
    obs = openweather.obs_from_forecast_3h(fixture("owm_forecast_3h.json"))
    assert len(obs) == 4
    first, second = obs[0], obs[1]
    assert first.time_utc == datetime(2026, 11, 8, 21, tzinfo=timezone.utc)
    assert first.temp_c == 24.1 and first.rh_pct == 18
    assert first.gust_ms == 7.2 and second.gust_ms is None
    assert first.precip_mm_per_h == 0.0          # rain absent → 0
    assert second.precip_mm_per_h == pytest.approx(0.5)  # rain["3h"] = 1.5 → 0.5 mm/h


def test_units_and_direction_unchanged():
    first = openweather.obs_from_forecast_3h(fixture("owm_forecast_3h.json"))[0]
    assert first.wind_speed_ms == 5.0    # no × 3.6
    assert first.wind_dir_deg == 270     # no + 180


def test_onecall_and_current_mapping():
    hourly = openweather.obs_from_onecall_hourly(fixture("owm_onecall_hourly.json"))
    assert len(hourly) == 9
    assert hourly[3].precip_mm_per_h == 0.4  # rain["1h"] as-is
    assert hourly[0].wind_dir_deg == 350 and hourly[0].gust_ms == 8.0 and hourly[1].gust_ms is None
    (current,) = openweather.obs_from_current(fixture("owm_current.json"))
    assert current.wind_speed_ms == 4.8 and current.wind_dir_deg == 275
    assert current.time_utc == datetime(2026, 11, 8, 19, 55, tzinfo=timezone.utc)


@pytest.mark.parametrize("field, value", [("wind_speed_ms", 61), ("rh_pct", 101), ("temp_c", -51), ("precip_mm_per_h", -0.1), ("wind_dir_deg", 361)])
def test_out_of_range_raises(field, value):
    args = dict(time_utc=T0, wind_speed_ms=5, wind_dir_deg=90, temp_c=20, rh_pct=30, precip_mm_per_h=0)
    args[field] = value
    with pytest.raises(WeatherRangeError, match=field):
        make_obs(**args)


def test_direction_360_normalised():
    assert make_obs(T0, 5, 360, 20, 30, 0).wind_dir_deg == 0


def test_naive_time_rejected():
    with pytest.raises(ValueError, match="naive"):
        make_obs(datetime(2026, 11, 8, 20), 5, 90, 20, 30, 0)


def test_merge_prefers_forecast_on_same_timestamp():
    anchor = [make_obs(T0, 1, 90, 20, 30, 0)]
    forecast = [make_obs(T0, 9, 180, 20, 30, 0)]
    (merged,) = merge_obs(anchor, forecast)
    assert merged.wind_speed_ms == 9


def mock_owm(rsps, forecast_status=200):
    base_fc, _ = openweather.ENDPOINTS["forecast-3h"]
    base_cur, _ = openweather.ENDPOINTS["current"]
    rsps.add(responses.GET, base_fc, json=fixture("owm_forecast_3h.json"), status=forecast_status)
    rsps.add(responses.GET, base_cur, json=fixture("owm_current.json"))


@responses.activate
def test_live_fetch_caches_without_key(tmp_path, monkeypatch, caplog):
    tmp_path = tmp_path / "cache"
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm(responses)
    caplog.set_level(logging.DEBUG)
    obs, source = fetch_weather(LAT, LON, "openweather:forecast-3h", cache_dir=tmp_path)

    assert obs[0].time_utc == datetime(2026, 11, 8, 19, 55, tzinfo=timezone.utc)  # current anchors t0
    assert len(obs) == 5
    assert source["provider"] == "openweather" and source["endpoint"] == "forecast-3h"
    assert source["fetched_at"].endswith("Z") and "note" in source
    assert all(c.request.params["units"] == "metric" for c in responses.calls)

    cached = sorted(tmp_path.iterdir())
    assert [p.name.split("_")[1] for p in cached] == ["current", "forecast-3h"]
    for p in cached:
        assert KEY not in p.read_text()
        assert "appid" not in load_raw(p)["url"]
    assert KEY not in caplog.text

    # cache:<path> and cache:latest replay the same observations offline, anchor included.
    replay, replay_source = fetch_weather(LAT, LON, f"cache:{source['cache_path']}")
    assert replay == obs
    assert replay_source["fetched_at"] == source["fetched_at"]
    latest, _ = fetch_weather(LAT, LON, "cache:latest", cache_dir=tmp_path)
    assert latest == obs


@responses.activate
def test_live_key_read_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"OPENWEATHER_API_KEY={KEY}\n")
    monkeypatch.setattr(sources, "REPO_ENV_FILE", env)
    mock_owm(responses)
    fetch_weather(LAT, LON, "openweather:forecast-3h", cache_dir=tmp_path / "cache")
    assert all(c.request.params["appid"] == KEY for c in responses.calls)


def test_cache_latest_without_cache_is_clear(tmp_path):
    with pytest.raises(FileNotFoundError, match="no cached forecast"):
        fetch_weather(LAT, LON, "cache:latest", cache_dir=tmp_path)


@responses.activate
def test_401_not_retried_and_key_not_leaked(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm(responses, forecast_status=401)
    with pytest.raises(openweather.OpenWeatherError, match="forecast-3h.*HTTP 401") as err:
        fetch_weather(LAT, LON, "openweather:forecast-3h", cache_dir=tmp_path)
    assert KEY not in str(err.value)
    assert len(responses.calls) == 1


@responses.activate
def test_5xx_retried_then_succeeds():
    base, _ = openweather.ENDPOINTS["current"]
    responses.add(responses.GET, base, status=503)
    responses.add(responses.GET, base, status=502)
    responses.add(responses.GET, base, json=fixture("owm_current.json"))
    raw = openweather.fetch_raw("current", LAT, LON, KEY)
    assert raw["wind"]["speed"] == 4.8
    assert len(responses.calls) == 3


@responses.activate
def test_5xx_gives_up_after_retries():
    base, _ = openweather.ENDPOINTS["current"]
    for _ in range(3):
        responses.add(responses.GET, base, status=500)
    with pytest.raises(openweather.OpenWeatherError, match="current failed after 3 attempts: HTTP 500"):
        openweather.fetch_raw("current", LAT, LON, KEY)


def test_missing_key_is_clear():
    with pytest.raises(RuntimeError, match="OPENWEATHER_API_KEY"):
        fetch_weather(LAT, LON, "openweather:forecast-3h")


def test_canned_needs_t0():
    with pytest.raises(ValueError, match="t0"):
        fetch_weather(LAT, LON, "canned:whatever.json")
