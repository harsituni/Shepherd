"""Public execution: run_simulation(scenario) -> immutable SimulationResult."""
import hashlib
import json

import numpy as np
from shapely.geometry import Point

from backend.sim.engine import ensemble
from backend.sim.engine.contracts import load_scenario
from backend.sim.engine.grid import build_grid, domain_mask, seed_mask, to_utm
from backend.sim.engine.result import SimulationResult
from backend.sim.engine.spread import compute_arrival
from backend.sim.engine.weather import build_weather_table, spread_bearing

ENGINE_VERSION = '0.2.0'
ASSUMPTIONS = [
    'Uniform M-1/M-2 fuel and fixed conifer share, FFMC and BUI.',
    'Temperature, humidity and precipitation do not change moisture.',
    'Zero slope; instantaneous equilibrium spread, no acceleration phase.',
    'All domain cells burnable; no explicit barriers, suppression or long-range spotting.',
    'Spatially uniform wind, interpolated as vectors over forecast time.',
    'Wind bearings use UTM grid north; grid convergence is ignored.',
    '16-direction spatial stencil; cell arrival represents the whole cell.',
    'Directional ROS is linearly interpolated between integration knots.',
    'These assumptions do not guarantee a conservative bound on real fire spread.',
]


def run_simulation(scenario) -> SimulationResult:
    """Deterministic full recomputation from initial ignition/perimeter at t0.

    Accepts validated Scenario, dict, JSON string or Path. No HTTP, implicit
    weather fetches, file writes, active state, or incremental continuation.
    """
    return _compute(scenario)


def _compute(scenario, *, mock=False):
    sc = load_scenario(scenario)
    grid = build_grid(sc.bbox, sc.cell_m)
    if grid.rows * grid.cols > 2_000_000:
        raise ValueError('grid exceeds 2 million cells; increase cell_m or reduce bbox')
    initial = sc.initial_perimeter.to_shapely() if sc.initial_perimeter else Point(sc.ignition.lon, sc.ignition.lat)
    initial_utm = to_utm(initial)
    seeds = seed_mask(initial_utm, grid)
    burnable = domain_mask(sc.bbox, grid)
    members = ensemble.make_members(sc.weather, sc.n_ensemble, seed=sc.ensemble_seed)
    if mock:
        from backend.sim.engine.mock import mock_arrival
        arrivals = [mock_arrival(seeds, grid, (initial_utm.centroid.x, initial_utm.centroid.y),
                                 spread_bearing(sc.weather[0].wind_dir_deg), sc.horizon_min)]
        members = members[:1]
    else:
        arrivals = [compute_arrival(seeds, burnable,
                    build_weather_table(m.weather, sc.fbp, sc.horizon_min, sc.integration_step_min),
                    sc.cell_m, sc.horizon_min) for m in members]
    p50, p10 = ensemble.combine(arrivals, sc.horizon_min)
    canonical = json.dumps(sc.model_dump(mode='json', by_alias=True), sort_keys=True, allow_nan=False)
    meta = {
        'schema': 'shepherd.engine.result/v1', 'engine_version': ENGINE_VERSION,
        'scenario_id': sc.scenario_id, 'run_id': sc.run_id, 't0': sc.t0.isoformat().replace('+00:00','Z'),
        'scenario_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'mode': 'mock' if mock else 'fbp', 'execution_mode': 'recompute', 'revision_of': sc.revision_of,
        'bbox': list(sc.bbox), 'domain_crs': 'EPSG:4326', 'grid_crs': 'EPSG:32612',
        'origin_xy': [grid.origin_x, grid.origin_y], 'origin_is': 'top-left',
        'rows': grid.rows, 'cols': grid.cols, 'cell_m': sc.cell_m,
        'horizon_min': sc.horizon_min, 'step_min': sc.step_min,
        'integration_step_min': sc.integration_step_min, 'time_unit': 'minutes since t0',
        'weather_coverage_min': [sc.weather[0].t_min, sc.weather[-1].t_min],
        'weather_end_policy': sc.weather_end_policy,
        'weather_extrapolated': sc.weather[-1].t_min < sc.horizon_min,
        'weather_source': sc.weather_source, 'forecast_steps': len(sc.weather),
        'fbp': sc.fbp.model_dump(),
        'n_ensemble': len(arrivals), 'ensemble_seed': sc.ensemble_seed,
        'ensemble_quantile_method': 'inverted_cdf; unreached members count as infinity',
        'members': [{'wind_factor': m.wind_factor, 'dir_offset_deg': m.dir_offset_deg} for m in members],
        'seed_cells': int(seeds.sum()), 'cells_reached_p50': int(np.isfinite(p50).sum()),
        'domain_boundary_reached': bool(np.any(np.isfinite(p50) & _boundary(burnable))),
        'assumptions': ASSUMPTIONS + (['MOCK: fixed analytic ellipse; not FBP.'] if mock else []),
    }
    return SimulationResult(grid, sc.bbox, sc.horizon_min, p50, p10,
                            json.dumps(meta, allow_nan=False), canonical)


def _boundary(mask):
    padded = np.pad(mask, 1)
    interior = (padded[1:-1, :-2] & padded[1:-1, 2:] & padded[:-2, 1:-1] & padded[2:, 1:-1])
    return mask & ~interior
