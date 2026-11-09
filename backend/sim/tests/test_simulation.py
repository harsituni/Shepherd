import copy
from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from pydantic import ValidationError

from backend.sim.engine import run_simulation
from backend.sim.engine.grid import TO_UTM


def scenario(**updates):
    data={'schema':'v1','scenario_id':'contract','run_id':'contract-r1','t0':'2026-11-08T20:00:00Z',
          'horizon_min':360,'step_min':30,'bbox':[-113.71,53.49,-113.59,53.57],
          'ignition':{'lat':53.535,'lon':-113.663},'cell_m':100,
          'weather':[{'t_min':t,'wind_speed_ms':7,'wind_dir_deg':270,'temp_c':20,'rh_pct':20,'precip_mm':0}
                     for t in (0,360)]}
    data.update(updates)
    return data


def arrival_at(result,lat,lon):
    row,col=result.grid.cell_of(*TO_UTM.transform(lon,lat))
    return result.arrival_grid()[row,col]


@pytest.fixture(scope='module')
def result():
    return run_simulation(scenario())


def test_fire_spreads_downwind_within_the_horizon(result):
    a=result.arrival_grid()
    assert a.shape==result.grid.shape and result.horizon_min==360
    assert arrival_at(result,53.535,-113.663)==0
    assert np.nanmax(a)<=360 and np.isnan(a).any()
    assert arrival_at(result,53.535,-113.62)<360          # east: downwind of a west wind
    assert np.isnan(arrival_at(result,53.535,-113.705))   # upwind edge


def test_result_cannot_be_mutated(result):
    with pytest.raises(ValueError):result.arrival_grid()[0,0]=0
    with pytest.raises(ValueError):result.arrival_grid().setflags(write=True)
    with pytest.raises(FrozenInstanceError):result.horizon_min=1


def test_deterministic_and_wind_dependent(result):
    before=result.arrival_grid().tobytes()
    again=run_simulation(copy.deepcopy(scenario()))
    np.testing.assert_array_equal(result.arrival_grid(),again.arrival_grid())
    changed=scenario();changed['weather'][1]['wind_dir_deg']=180
    assert run_simulation(changed).arrival_grid().tobytes()!=before
    assert result.arrival_grid().tobytes()==before


@pytest.mark.parametrize('change', [
    {'cell_m':0}, {'integration_step_min':0},
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
    assert np.nanmax(run_simulation(data).arrival_grid())>0


def test_ignition_on_closed_southern_grid_boundary():
    r=run_simulation(scenario(bbox=[-111.01,0,-110.99,.01],ignition={'lat':0,'lon':-111}))
    assert np.nanmin(r.arrival_grid())==0
