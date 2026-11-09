from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

import pytest

from backend.sim.engine import fbp
from backend.sim.weatherpipe.obs import make_obs, WeatherRangeError
from backend.sim.weatherpipe.resample import build_weather_series,coverage_metadata,CoverageError

FIXTURE=json.loads((Path(__file__).parent/'fixtures/fbp_reference.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'])
def test_independent_decimal_fbp_fixtures(case):
    actual=fbp.spread_rates(**case['input'])
    for field,value in case['expected'].items():
        assert float(getattr(actual,field))==pytest.approx(value,rel=1e-11,abs=1e-12)


@pytest.mark.parametrize('field',['wind_speed_ms','wind_dir_deg','temp_c','rh_pct','precip_mm_per_h','gust_ms'])
@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_normalization_rejects_nonfinite(field,bad):
    args=dict(time_utc=datetime(2026,1,1,tzinfo=timezone.utc),wind_speed_ms=5,wind_dir_deg=270,
              temp_c=20,rh_pct=30,precip_mm_per_h=0,gust_ms=6)
    args[field]=bad
    with pytest.raises(WeatherRangeError):make_obs(**args)


def test_missing_interior_weather_and_duplicates_fail():
    t0=datetime(2026,1,1,tzinfo=timezone.utc)
    def obs(t):return make_obs(t0+timedelta(minutes=t),5,270,20,30,0)
    with pytest.raises(CoverageError,match='interior'):build_weather_series([obs(0),obs(600)],t0,360)
    with pytest.raises(ValueError,match='duplicate'):build_weather_series([obs(0),obs(0)],t0,60)
    with pytest.raises(CoverageError):build_weather_series([],t0,60)
    series=build_weather_series([obs(60),obs(120)],t0,180)
    meta=coverage_metadata([obs(60),obs(120)],t0,180)
    assert meta['start_hold_min']==60 and meta['end_hold_min']==60
    assert len(series)==4


def test_malformed_provider_json_and_timeout_retries(monkeypatch):
    import requests
    import responses
    from backend.sim.weatherpipe import openweather
    monkeypatch.setattr(openweather.time,'sleep',lambda _:None)
    url=openweather.ENDPOINTS['forecast-3h'][0]
    with responses.RequestsMock() as mock:
        mock.add(responses.GET,url,body='invalid',status=200)
        with pytest.raises(openweather.OpenWeatherError,match='invalid JSON'):
            openweather.fetch_raw('forecast-3h',53.5,-113.5,'fixture-key')
    with responses.RequestsMock() as mock:
        for _ in range(3):mock.add(responses.GET,url,body=requests.Timeout('fixture timeout'))
        with pytest.raises(openweather.OpenWeatherError,match='3 attempts'):
            openweather.fetch_raw('forecast-3h',53.5,-113.5,'fixture-key')
        assert len(mock.calls)==3
