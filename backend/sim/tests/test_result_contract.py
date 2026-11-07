import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
import socket

import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import Point, shape

from backend.sim.engine import run_simulation, SimulationResult
from backend.sim.engine.contracts import load_scenario
from backend.sim.engine.grid import TO_WGS84, TO_UTM


def scenario(**updates):
    data={'schema':'v1','scenario_id':'contract','run_id':'contract-r1','t0':'2026-11-08T20:00:00Z',
          'horizon_min':360,'step_min':30,'bbox':[-113.71,53.49,-113.59,53.57],
          'ignition':{'lat':53.535,'lon':-113.663},'cell_m':100,'n_ensemble':1,
          'weather':[{'t_min':t,'wind_speed_ms':7,'wind_dir_deg':270,'temp_c':20,'rh_pct':20,'precip_mm':0}
                     for t in (0,360)]}
    data.update(updates)
    return data


@pytest.fixture(scope='module')
def result():
    return run_simulation(scenario())


def centre(result,row,col):
    return TO_WGS84.transform(result.grid.origin_x+(col+.5)*result.grid.cell_m,
                              result.grid.origin_y-(row+.5)*result.grid.cell_m)


def test_arrival_after_120_is_preserved(result):
    a=result.arrival_grid()
    for row,col in np.argwhere((a>120)&(a<300)):
        lon,lat=centre(result,row,col)
        q=result.arrival_at(lat,lon,minute=360)
        if q.status=='arrival':break
    assert q.arrival_min>120 and q.burned is True
    before=result.arrival_at(lat,lon,minute=10)
    assert before.arrival_min==q.arrival_min and before.burned is False
    assert result.arrival_at(lat,lon,minute=1000).burned is True


def test_unknown_and_domain_statuses(result):
    assert result.arrival_at(53.535,-113.663,minute=0).burned is True
    assert result.arrival_at(53.0,-113.0).status=='outside_domain'
    assert result.arrival_at(float('nan'),-113.6).status=='invalid_input'
    assert result.arrival_at(53.5,float('inf')).status=='invalid_input'
    assert result.arrival_at(53.5,-113.6,minute=-1).status=='invalid_input'
    assert result.arrival_at(53.5,-113.6,band='wrong').status=='invalid_input'
    q=result.arrival_at(53.491,-113.709,minute=360)
    assert q.status=='not_reached' and q.burned is False
    assert result.arrival_at(53.491,-113.709,minute=500).burned is None
    w,s,e,n=result.bbox
    for lon,lat in [(w,s),(w,n),(e,s),(e,n),((w+e)/2,s)]:
        assert result.arrival_at(lat,lon).status in ('arrival','not_reached')
        x,y=TO_UTM.transform(lon,lat)
        assert TO_WGS84.transform(x,y)==pytest.approx((lon,lat),abs=1e-8)
    assert result.arrival_at(s-1e-9,w).status=='outside_domain'


def test_result_readers_and_export_cannot_mutate(result,tmp_path):
    before=result.arrival_grid().tobytes()
    with pytest.raises(ValueError):result.arrival_grid()[0,0]=0
    with pytest.raises(ValueError):result.arrival_grid().setflags(write=True)
    with pytest.raises(FrozenInstanceError):result.horizon_min=1
    meta=result.metadata;meta['fbp']['ffmc']=0
    sc=result.scenario;sc['weather'][0]['wind_speed_ms']=0
    expected=[result.perimeter_at(t*30) for t in range(7)]
    def read(i):
        frame=result.perimeter_at((i%7)*30)
        assert frame == expected[i%7]
        frame['properties']['t_min']=-1
        return result.arrival_at(53.535,-113.663,minute=200)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(q.burned for q in pool.map(read,range(40)))
    result.export(tmp_path/'run',minutes=[0,120,360])
    assert result.arrival_grid().tobytes()==before
    assert result.metadata['fbp']['ffmc']==92
    assert result.scenario['weather'][0]['wind_speed_ms']==7


def test_valid_geojson_monotonic_growth_and_bounds(result):
    frames=result.frames_at([0,30,60,120,240,360])
    previous=None
    for f in frames['features']:
        geom=shape(f['geometry'])
        assert geom.is_valid and not geom.is_empty
        w,s,e,n=geom.bounds
        assert result.bbox[0]<=w<=e<=result.bbox[2]
        assert result.bbox[1]<=s<=n<=result.bbox[3]
        if previous is not None:
            assert previous.difference(geom).area<1e-12
        previous=geom
    for t in (-1,361,float('nan')):
        with pytest.raises(ValueError):result.perimeter_at(t)


def test_determinism_revision_and_ensemble_seed(tmp_path):
    base=scenario(n_ensemble=3,ensemble_seed=42)
    a=run_simulation(base);b=run_simulation(copy.deepcopy(base))
    np.testing.assert_array_equal(a.arrival_grid(),b.arrival_grid())
    assert a.frames_at([60,120])==b.frames_at([60,120])
    assert a.metadata==b.metadata
    a.export(tmp_path/'a',minutes=[0,120]);b.export(tmp_path/'b',minutes=[0,120])
    for path in (tmp_path/'a').iterdir():
        assert path.read_bytes()==(tmp_path/'b'/path.name).read_bytes()
    changed=copy.deepcopy(base);changed['run_id']='contract-r2';changed['revision_of']=base['run_id']
    c=run_simulation(changed)
    np.testing.assert_array_equal(a.arrival_grid(),c.arrival_grid())
    assert a.metadata['members']==c.metadata['members']
    before=a.arrival_grid().tobytes()
    changed['weather'][1]['wind_dir_deg']=180
    d=run_simulation(changed)
    assert d.metadata['execution_mode']=='recompute'
    assert d.metadata['revision_of']=='contract-r1'
    assert d.arrival_grid().tobytes()!=before
    assert a.arrival_grid().tobytes()==before
    with pytest.raises(ValidationError):run_simulation(scenario(execution_mode='continue'))


def test_export_load_manifest_and_no_overwrite(result,tmp_path):
    folder=tmp_path/'run';manifest=result.export(folder,minutes=[0,120,360])
    assert manifest['schema']=='shepherd.engine.export/v1'
    assert manifest['horizon_min']==360
    assert manifest['bbox']==list(result.bbox)
    loaded=SimulationResult.load(folder)
    np.testing.assert_array_equal(loaded.arrival_grid(),result.arrival_grid())
    assert loaded.arrival_at(53.535,-113.663,minute=140)==result.arrival_at(53.535,-113.663,minute=140)
    assert loaded.frames_at([0,120])==result.frames_at([0,120])
    with pytest.raises(FileExistsError):result.export(folder)
    assert (folder/'manifest.json').exists()
    (folder/'arrival_p50.npy').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='integrity'):SimulationResult.load(folder)


@pytest.mark.parametrize('change', [
    {'cell_m':0}, {'integration_step_min':0}, {'ensemble_seed':-1},
    {'initial_perimeter':{'type':'Polygon','coordinates':[[[-113.7,53.5],[-113.6,53.5],[-113.6,53.6],[-113.7,53.5]]]}},
    {'bbox':[-120,53,-119,54]}, {'unknown_parameter':1},
    {'fbp':{'ffmc':float('nan')}}, {'ignition':{'lat':53,'lon':-113}},
])
def test_invalid_scenarios_fail_before_computation(change):
    with pytest.raises(ValidationError):run_simulation(scenario(**change))


def test_short_forecast_rejected_or_explicitly_held():
    data=scenario();data['weather']=data['weather'][:1]
    with pytest.raises(ValidationError,match='horizon'):run_simulation(data)
    data['weather_end_policy']='hold'
    result=run_simulation(data)
    assert result.metadata['weather_extrapolated'] is True
    assert result.metadata['weather_coverage_min']==[0,0]


def test_offline_canned_pipeline_export(tmp_path,monkeypatch):
    from backend.sim.engine.demo import demonstrate
    def blocked(*args,**kwargs):raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.delenv('OPENWEATHER_API_KEY',raising=False)
    summary=demonstrate(tmp_path/'demo')
    result=SimulationResult.load(tmp_path/'demo')
    assert result.metadata['mode']=='fbp'
    assert result.metadata['weather_source']['provider']=='canned'
    assert summary['queries']['ignition']['status']=='arrival'
    assert result.metadata['cells_reached_p50']>result.metadata['seed_cells']


def test_ignition_on_closed_southern_grid_boundary():
    data=scenario(bbox=[-111.01,0,-110.99,.01],ignition={'lat':0,'lon':-111})
    r=run_simulation(data)
    assert r.arrival_at(0,-111,minute=0).burned is True
    assert r.arrival_at(-1e-9,-111).status=='outside_domain'
