"""Independent traversal oracle, FIFO, and the audit's two-cell regression."""
import math

import numpy as np
import pytest

from backend.sim.engine.contracts import FbpParams, WeatherEntry
from backend.sim.engine.spread import DirectionalTravel, compute_arrival, neighbour_rates
from backend.sim.engine.weather import build_weather_table, WeatherTable


def entry(t, speed, direction):
    return WeatherEntry(t_min=t, wind_speed_ms=speed, wind_dir_deg=direction,
                        temp_c=20, rh_pct=20, precip_mm=0)


def reference_east_rate(t, weather):
    """Independent scalar equations + ray/ellipse intersection by bisection.

    No production weather, FBP, integration or inversion functions called.
    Used with default M-1/PC50/FFMC92/BUI90 parameters.
    """
    hi = next((i for i, w in enumerate(weather) if w.t_min >= t), len(weather)-1)
    lo = max(0, hi-1)
    a, b = weather[lo], weather[hi]
    f = 0 if a.t_min == b.t_min else (t-a.t_min)/(b.t_min-a.t_min)
    def uv(w):
        angle = math.radians(w.wind_dir_deg)
        return -w.wind_speed_ms*math.sin(angle), -w.wind_speed_ms*math.cos(angle)
    u0,v0=uv(a); u1,v1=uv(b)
    u,v=u0+(u1-u0)*f,v0+(v1-v0)*f
    ws=math.hypot(u,v)*3.6
    bearing=math.atan2(u,v)
    moisture=147.27723*9/151.5
    ff=91.9*math.exp(-.1386*moisture)*(1+moisture**5.31/49300000)
    be=math.exp(50*math.log(.8)*(1/90-1/50))
    def rate(wind):
        isi=.208*wind*ff
        return be*(55*(1-math.exp(-.0282*isi))**1.5+15*(1-math.exp(-.0232*isi))**1.6)
    head=rate(math.exp(.05039*ws) if ws<=40 else 12*(1-math.exp(-.0818*(ws-28))))
    back=rate(math.exp(-.05039*ws))
    lb=1+8.729*(1-math.exp(-.030*ws))**2.155
    major=(head+back)/2; minor=major/lb; offset=(head-back)/2
    theta=math.pi/2-bearing
    lo,hi=0.,head
    for _ in range(45):
        ray=(lo+hi)/2
        outside=((ray*math.cos(theta)-offset)/major)**2+(ray*math.sin(theta)/minor)**2>1
        if outside: hi=ray
        else: lo=ray
    return (lo+hi)/2


def reference_crossing(weather, distance, horizon, dt=.01):
    """March distance with midpoint quadrature; independent of cumulative inverse."""
    remaining=distance
    for t in np.arange(0,horizon,dt):
        rate=reference_east_rate(t+dt/2,weather)
        if rate*dt>=remaining:
            return t+remaining/rate
        remaining-=rate*dt
    return math.inf


def two_cells(weather, horizon, step):
    table=build_weather_table(weather,FbpParams(),horizon,step)
    return compute_arrival(np.array([[1,0]],bool),np.ones((1,2),bool),table,100,horizon)[0,1]


def test_original_hourly_wind_reversal_regression():
    weather=[entry(0,10,90),entry(60,10,90),entry(120,10,270),entry(180,10,270)]
    expected=reference_crossing(weather,100,180)
    actual=two_cells(weather,180,.25)
    assert 97 < expected < 99
    assert actual==pytest.approx(expected,abs=.005)


@pytest.mark.parametrize('winds', [
    [(0,0,270),(60,10,270),(180,10,270)],
    [(0,10,270),(60,0,270),(180,0,270)],
    [(0,8,90),(30,1,350),(60,9,270),(120,4,180),(180,6,270)],
])
def test_speed_changes_and_multiple_shifts_against_independent_reference(winds):
    weather=[entry(*w) for w in winds]
    expected=reference_crossing(weather,100,180)
    assert two_cells(weather,180,.25)==pytest.approx(expected,abs=.008)


def test_integration_converges():
    weather=[entry(0,10,90),entry(60,10,90),entry(120,10,270),entry(180,10,270)]
    expected=reference_crossing(weather,100,180,dt=.002)
    errors=[abs(float(two_cells(weather,180,s))-expected) for s in (4,1,.25)]
    assert errors[2]<errors[1]<errors[0]
    assert errors[-1]<.005


@pytest.mark.parametrize('rates,expected', [([0,0,10], 1+math.sqrt(.2)),
                                          ([1e-10,1e-10,10], 1+math.sqrt(.2)),
                                          ([0,0,0], math.inf)])
def test_zero_nearzero_and_renewed_spread(rates,expected):
    travel=DirectionalTravel([0,1,2],np.array(rates)[:,None])
    assert travel.arrival(0,0,1)==pytest.approx(expected,abs=1e-9)


def test_progress_preserved_across_zero_interval():
    travel=DirectionalTravel([0,1,2,3,4],np.array([2,0,0,0,2])[:,None])
    assert travel.arrival(0,0,1.5)==pytest.approx(3+math.sqrt(.5))
    assert travel.arrival(0,0,1)==pytest.approx(1)  # earliest edge of plateau
    tiny=DirectionalTravel([0,10],np.array([[1e-12],[1e-12]]))
    assert tiny.arrival(0,0,5e-12)==pytest.approx(5)


def test_fifo_for_all_directions_with_stops_and_reversals():
    weather=[entry(0,12,90),entry(20,0,0),entry(40,8,270),entry(80,2,180),entry(120,12,0)]
    table=build_weather_table(weather,FbpParams(),120,.25)
    travel=DirectionalTravel(table.times_min,neighbour_rates(table))
    for n in range(16):
        times=[travel.arrival(t,n,30) for t in np.linspace(0,120,501)]
        assert all(b>=a-1e-10 for a,b in zip(times,times[1:]))


def test_dijkstra_matches_independent_time_marching_line():
    # Isotropic R(t)=1+t; exact distance integral is t+t²/2.
    t=np.linspace(0,20,81); rates=1+t
    table=WeatherTable(rates*0,rates*0,rates,rates,rates,np.ones_like(t),rates*0,t)
    seeds=np.zeros((1,10),bool);seeds[0,0]=True
    actual=compute_arrival(seeds,np.ones_like(seeds),table,10,20)
    expected=np.sqrt(1+20*np.arange(10))-1
    np.testing.assert_allclose(actual[0],expected,atol=1e-6)


def test_zero_then_positive_can_leave_seed_after_wait():
    t=np.array([0.,10.,11.,30.]);r=np.array([0.,0.,10.,10.])
    table=WeatherTable(r*0,r*0,r,r,r,np.ones(4),r*0,t)
    actual=compute_arrival(np.array([[1,0]],bool),np.ones((1,2),bool),table,100,30)
    assert actual[0,1]==pytest.approx(20.5)
