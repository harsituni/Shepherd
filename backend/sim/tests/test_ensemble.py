import numpy as np
import pytest

from backend.sim.engine import ensemble
from backend.sim.engine.contracts import WeatherEntry

WEATHER = [
    WeatherEntry(t_min=0, wind_speed_ms=6, wind_dir_deg=270, temp_c=20, rh_pct=20, precip_mm=0),
    WeatherEntry(t_min=60, wind_speed_ms=8, wind_dir_deg=250, temp_c=20, rh_pct=20, precip_mm=0),
]


def test_member_zero_unperturbed_and_reproducible():
    a = ensemble.make_members(WEATHER, 5, "run-1")
    b = ensemble.make_members(WEATHER, 5, "run-1")
    assert a[0].weather == WEATHER
    assert [m.wind_factor for m in a] == [m.wind_factor for m in b]
    assert [m.dir_offset_deg for m in a] == [m.dir_offset_deg for m in b]
    for m in a[1:]:
        assert 0.6 <= m.wind_factor <= 1.5
        assert m.weather[1].wind_speed_ms == pytest.approx(8 * m.wind_factor)


def test_different_run_ids_differ():
    a = ensemble.make_members(WEATHER, 3, "run-1")
    b = ensemble.make_members(WEATHER, 3, "run-2")
    assert a[1].wind_factor != b[1].wind_factor


def test_combine_single_member():
    arr = np.array([[0, 5, np.nan]], dtype=np.float32)
    p50, p10 = ensemble.combine([arr], 60)
    np.testing.assert_array_equal(p50, p10)


def test_combine_treats_nan_as_never():
    nan = np.nan
    members = [np.array([[10, 10, nan, 20]], dtype=np.float32) for _ in range(9)]
    members.append(np.array([[1, nan, nan, nan]], dtype=np.float32))
    members.append(np.array([[2, nan, nan, nan]], dtype=np.float32))
    p50, p10 = ensemble.combine(members, 60)
    assert p50.dtype == np.float32
    assert p50[0, 0] == 10
    assert p10[0, 0] < 10
    assert p50[0, 1] == 10        # 9 of 11 members reached it
    assert np.isnan(p50[0, 2]) and np.isnan(p10[0, 2])
    assert p10[0, 3] == 20        # earliest decile still reached
