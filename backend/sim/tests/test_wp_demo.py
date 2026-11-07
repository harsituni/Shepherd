"""End to end: Edmonton config → weatherpipe demo → spread engine.

Live OpenWeather is mocked with saved fixture responses; nothing touches the network.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import responses

from backend.sim.engine.contracts import load_b1
from backend.sim.engine.run import run_engine
from backend.sim.weatherpipe import build, demo, openweather, sources

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = SCENARIOS / "edm-demo-1.json"
CANNED = f"canned:{SCENARIOS / 'edm-demo-1.weather.json'}"
T0 = "2026-11-08T20:00:00Z"  # matches the fixture responses
KEY = "sk-test-not-a-real-key-123"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setattr(sources, "REPO_ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(openweather.time, "sleep", lambda s: None)


def mock_owm():
    for endpoint, name in (("forecast-3h", "owm_forecast_3h.json"), ("current", "owm_current.json")):
        base, _ = openweather.ENDPOINTS[endpoint]
        responses.add(responses.GET, base, json=json.loads((FIXTURES / name).read_text()))


def run_both(out):
    arrivals = {}
    for name in ("scenario_r1.json", "scenario_r2.json"):
        result = run_engine(out / "contracts" / name, out / "runs")
        _, layers = load_b1(result["out_dir"])
        arrivals[result["run_id"]] = layers["arrival_p50"]
    return list(arrivals.values())


def assert_shift_changes_fire(a1, a2):
    shift_start = json.loads(CONFIG.read_text())["wind_shift"]["start_min"]
    np.testing.assert_array_equal(a1 <= shift_start, a2 <= shift_start)  # same until the shift
    assert not np.array_equal(np.isfinite(a1), np.isfinite(a2))          # different after it


@responses.activate
def test_live_demo_calls_openweather_then_engine(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    mock_owm()
    cache_dir = tmp_path / "cache"
    demo.main([str(CONFIG), "--t0", T0, "--out", str(tmp_path / "contracts"), "--cache-dir", str(cache_dir)])
    out = capsys.readouterr().out
    assert "weather: openweather forecast-3h" in out and "shifted" in out

    called = sorted(c.request.url.split("?")[0] for c in responses.calls)
    assert called == sorted(openweather.ENDPOINTS[e][0] for e in ("forecast-3h", "current"))
    lat, lon = (float(responses.calls[0].request.params[k]) for k in ("lat", "lon"))
    assert (lat, lon) == pytest.approx((53.5, -113.565))  # Edmonton bbox centroid

    r1 = json.loads((tmp_path / "contracts" / "scenario_r1.json").read_text())
    assert r1["scenario_id"] == "edm-demo-1" and r1["weather_source"]["provider"] == "openweather"
    assert all(KEY not in p.read_text() for p in cache_dir.iterdir())
    assert_shift_changes_fire(*run_both(tmp_path))

    # Network gone: the same demo replays from the cache.
    responses.reset()
    demo.main([str(CONFIG), "--t0", T0, "--out", str(tmp_path / "replay"), "--cache-dir", str(cache_dir),
               "--source", "cache:latest"])
    replay = json.loads((tmp_path / "replay" / "scenario_r1.json").read_text())
    assert replay["weather"] == r1["weather"]
    assert len(responses.calls) == 0


def test_canned_demo_offline(tmp_path, capsys):
    demo.main([str(CONFIG), "--t0", T0, "--out", str(tmp_path / "contracts"), "--source", CANNED])
    assert "weather: canned" in capsys.readouterr().out
    r1 = json.loads((tmp_path / "contracts" / "scenario_r1.json").read_text())
    r2 = json.loads((tmp_path / "contracts" / "scenario_r2.json").read_text())
    assert r1["t0"] == r2["t0"] == T0
    assert r1["run_id"] == "edm-demo-1-r1" and r2["run_id"] == "edm-demo-1-r2"
    assert_shift_changes_fire(*run_both(tmp_path))


def test_demo_without_key_explains(tmp_path):
    with pytest.raises(RuntimeError, match="cache:latest"):
        demo.make_demo(CONFIG, demo.parse_utc(T0), tmp_path, cache_dir=tmp_path / "cache")


def test_build_numbers_runs(tmp_path):
    t0 = demo.parse_utc(T0)
    first = build.build_live(CONFIG, CANNED, t0, tmp_path)
    second = build.build_live(CONFIG, CANNED, t0, tmp_path)
    assert first.parent.name == "edm-demo-1-r1" and second.parent.name == "edm-demo-1-r2"
    result = run_engine(second, tmp_path)
    assert Path(result["out_dir"]) == second.parent
