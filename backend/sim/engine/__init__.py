"""Standalone FBP engine. Public interface: run_simulation, SimulationResult, ArrivalQuery."""
# Lazy import keeps numerical submodules usable without circular imports.
def run_simulation(scenario):
    from backend.sim.engine.simulation import run_simulation as run
    return run(scenario)

from backend.sim.engine.result import ArrivalQuery, SimulationResult

__all__ = ['run_simulation', 'SimulationResult', 'ArrivalQuery']
