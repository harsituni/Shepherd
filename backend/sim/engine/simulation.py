"""run_simulation(scenario) -> immutable SimulationResult: one FBP fire from t0.

Model assumptions (none of them a conservative bound on real fire spread):
uniform M-1/M-2 fuel with fixed conifer share, FFMC and BUI; temperature, humidity
and rain don't change moisture; flat ground, instantaneous equilibrium spread;
every domain cell burnable (no barriers, suppression or spotting); one uniform
wind, interpolated as vectors over time, with bearings on UTM grid north; a
16-direction stencil where one arrival time stands for the whole cell.
"""

from shapely.geometry import Point

from backend.sim.engine.contracts import load_scenario
from backend.sim.engine.grid import build_grid, domain_mask, seed_mask, to_utm
from backend.sim.engine.result import SimulationResult
from backend.sim.engine.spread import compute_arrival
from backend.sim.engine.weather import build_weather_table

MAX_CELLS = 2_000_000


def run_simulation(scenario) -> SimulationResult:
    """Deterministic full recomputation from the ignition/perimeter at t0.

    Accepts a Scenario or a dict. No HTTP, weather fetches, file writes or state.
    """
    sc = load_scenario(scenario)
    grid = build_grid(sc.bbox, sc.cell_m)
    if grid.rows * grid.cols > MAX_CELLS:
        raise ValueError('grid exceeds 2 million cells; increase cell_m or reduce bbox')
    initial = sc.initial_perimeter.to_shapely() if sc.initial_perimeter else Point(sc.ignition.lon, sc.ignition.lat)
    seeds = seed_mask(to_utm(initial), grid)
    burnable = domain_mask(sc.bbox, grid)
    table = build_weather_table(sc.weather, sc.fbp, sc.horizon_min, sc.integration_step_min)
    arrival = compute_arrival(seeds, burnable, table, sc.cell_m, sc.horizon_min)
    return SimulationResult(grid, sc.bbox, sc.horizon_min, arrival)
