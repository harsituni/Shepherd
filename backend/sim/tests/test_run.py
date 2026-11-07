import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import shape

from backend.sim.engine.contracts import load_b1, load_scenario
from backend.sim.engine.run import main, run_engine

EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "scenario_a.example.json"


def example():
    return json.loads(EXAMPLE.read_text())


def small_scenario(run_id, weather):
    """2 h run on a small bbox around an ignition near Edmonton."""
    lon, lat, d = -113.66, 53.535, 0.002
    if weather[-1][0] < 120:
        weather = [*weather, (120, *weather[-1][1:])]
    return {
        "schema": "v1",
        "scenario_id": "test",
        "run_id": run_id,
        "t0": "2026-11-08T20:00:00Z",
        "horizon_min": 120,
        "step_min": 15,
        "bbox": [-113.76, 53.47, -113.56, 53.60],
        "initial_perimeter": {
            "type": "Polygon",
            "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]],
        },
        "weather": [
            {"t_min": t, "wind_speed_ms": s, "wind_dir_deg": w, "temp_c": 20, "rh_pct": 20, "precip_mm": 0}
            for t, s, w in weather
        ],
        "n_ensemble": 1,
    }


def frame_shapes(frames_path, band="p50"):
    fc = json.loads(Path(frames_path).read_text())
    return [(f["properties"]["t_min"], shape(f["geometry"])) for f in fc["features"] if f["properties"]["band"] == band]


def all_coords(coords):
    if isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from all_coords(c)


@pytest.fixture(scope="module")
def example_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("runs")
    started = time.perf_counter()
    result = run_engine(EXAMPLE, out)
    return result, time.perf_counter() - started


def test_example_run_under_30s(example_run):
    _, elapsed = example_run
    assert elapsed < 30


def test_b1_outputs(example_run):
    result, _ = example_run
    header, arrays = load_b1(result["out_dir"])
    assert header.run_id == "fmm-demo-1-r1"
    assert header.crs == "EPSG:32612" and header.origin_is == "top-left"
    assert header.origin_xy[0] % header.cell_m == 0 and header.origin_xy[1] % header.cell_m == 0
    p50, p10 = arrays["arrival_p50"], arrays["arrival_p10"]
    assert p50.shape == (header.rows, header.cols) and p50.dtype == np.float32
    assert np.isnan(p50).any() and (p50 == 0).any()
    assert np.nanmax(p50) <= 360
    np.testing.assert_array_equal(p50, p10)  # n_ensemble = 1


def test_b2_frames(example_run):
    result, _ = example_run
    fc = json.loads(Path(result["frames_path"]).read_text())
    assert fc["type"] == "FeatureCollection" and fc["run_id"] == "fmm-demo-1-r1"
    assert len(fc["features"]) == 360 // 15 + 1
    assert [f["properties"]["t_min"] for f in fc["features"]] == list(range(0, 361, 15))
    min_lon, min_lat, max_lon, max_lat = example()["bbox"]
    for f in fc["features"]:
        assert f["geometry"]["type"] == "MultiPolygon"
        for lon, lat in all_coords(f["geometry"]["coordinates"]):
            assert min_lon - 1e-6 <= lon <= max_lon + 1e-6
            assert min_lat - 1e-6 <= lat <= max_lat + 1e-6
    areas = [geom.area for _, geom in frame_shapes(result["frames_path"])]
    assert areas[0] > 0
    assert all(b >= a * 0.999 for a, b in zip(areas, areas[1:]))  # cumulative, allowing simplify noise


def test_run_meta_lists_assumptions(example_run):
    result, _ = example_run
    meta = json.loads((Path(result["out_dir"]) / "run_meta.json").read_text())
    assert meta["mode"] == "fbp" and meta["fbp"]["fuel_type"] == "M-1"
    assert any("convergence" in a for a in meta["assumptions"])


def test_wind_from_west_moves_fire_east(tmp_path):
    result = run_engine(small_scenario("west", [(0, 7, 270)]), tmp_path)
    frames = frame_shapes(result["frames_path"])
    lons = [geom.centroid.x for _, geom in frames]
    lats = [geom.centroid.y for _, geom in frames]
    assert lons[-1] - lons[0] > 0.01
    assert all(b >= a - 1e-6 for a, b in zip(lons, lons[1:]))
    assert abs(lats[-1] - lats[0]) < 0.002


def test_wind_shift_bends_perimeter(tmp_path):
    steady = run_engine(small_scenario("steady", [(0, 7, 270), (120, 7, 270)]), tmp_path)
    shifted = run_engine(small_scenario("shifted", [(0, 7, 270), (60, 7, 270), (61, 7, 180), (120, 7, 180)]), tmp_path)
    end_steady = frame_shapes(steady["frames_path"])[-1][1]
    end_shift = frame_shapes(shifted["frames_path"])[-1][1]
    # Southerly wind in hour 2 pushes the north edge ~0.5 km+ further than steady westerly.
    assert end_shift.bounds[3] - end_steady.bounds[3] > 0.005
    assert end_shift.bounds[2] < end_steady.bounds[2]  # and the eastward run stops
    _, a_steady = load_b1(steady["out_dir"])
    _, a_shift = load_b1(shifted["out_dir"])
    np.testing.assert_array_equal(  # identical until the shift
        a_steady["arrival_p50"] <= 60, a_shift["arrival_p50"] <= 60
    )


def test_deterministic(tmp_path):
    scenario = small_scenario("det", [(0, 6, 300), (60, 8, 240)])
    run_engine(scenario, tmp_path / "a")
    run_engine(scenario, tmp_path / "b")
    for name in ("arrival_p50.npy", "arrival_p10.npy", "frames.geojson", "b1_header.json"):
        assert (tmp_path / "a" / "det" / name).read_bytes() == (tmp_path / "b" / "det" / name).read_bytes()


def test_ensemble_p10_earlier_than_p50(tmp_path):
    scenario = small_scenario("ens", [(0, 7, 270)])
    scenario["n_ensemble"] = 7
    result = run_engine(scenario, tmp_path)
    _, arrays = load_b1(result["out_dir"])
    p50, p10 = arrays["arrival_p50"], arrays["arrival_p10"]
    both = np.isfinite(p50) & np.isfinite(p10)
    assert np.all(p10[both] <= p50[both])
    assert np.isfinite(p10).sum() >= np.isfinite(p50).sum()
    bands = {f["properties"]["band"] for f in json.loads(Path(result["frames_path"]).read_text())["features"]}
    assert bands == {"p50", "p10"}


def test_mock_run(tmp_path):
    result = run_engine(EXAMPLE, tmp_path, mock=True)
    header, arrays = load_b1(result["out_dir"])
    p50 = arrays["arrival_p50"]
    assert np.isnan(p50).any() and np.nanmax(p50) <= 360
    frames = frame_shapes(result["frames_path"])
    assert len(frames) == 25
    assert frames[-1][1].centroid.x > frames[1][1].centroid.x  # t=0 wind from 270 → east


def test_cli(tmp_path, capsys):
    main([str(EXAMPLE), "--out", str(tmp_path), "--mock", "--cell-m", "200"])
    assert json.loads(capsys.readouterr().out)["run_id"] == "fmm-demo-1-r1"
    header, _ = load_b1(tmp_path / "fmm-demo-1-r1")
    assert header.cell_m == 200


@pytest.mark.parametrize("path, field", [
    (("weather",), "weather"),
    (("weather", 0, "wind_speed_ms"), "wind_speed_ms"),
    (("initial_perimeter",), "initial_perimeter"),
])
def test_missing_field_named(path, field):
    data = example()
    target = data
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValidationError, match=field):
        load_scenario(data)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(schema="v2"), "schema"),
    (lambda d: d.update(t0="2026-11-08T20:00:00+02:00"), "UTC"),
    (lambda d: d["weather"].reverse(), "t_min"),
    (lambda d: d["fbp"].update(fuel_type="C-2"), "fuel_type"),
    (lambda d: d.update(bbox=[-110.0, 50.0, -109.9, 50.1]), "outside bbox"),
])
def test_bad_scenario_rejected(change, message):
    data = copy.deepcopy(example())
    change(data)
    with pytest.raises(ValidationError, match=message):
        load_scenario(data)


def test_fbp_block_optional():
    data = example()
    del data["fbp"]
    assert load_scenario(data).fbp.ffmc == 92
