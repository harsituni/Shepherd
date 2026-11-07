# Standalone forecast-driven wildfire engine

From the repository root, with dependencies installed in `backend/.venv`:

```sh
backend/.venv/bin/python -m pip install -r backend/sim/requirements.txt
backend/.venv/bin/python -m backend.sim.engine.demo
```

The second command is a complete **offline** demonstration. It loads the deterministic
Edmonton canned weather fixture, builds/validates the scenario, runs actual FBP spread,
exports arrivals and 25 frames over six hours, performs four representative queries,
and prints the output directory. Each invocation chooses a fresh
`backend/sim/runs/offline-demo-rN` directory. No API key, server, or frontend is needed.
`demo.py` is also the Python usage example. Generated runs are ignored by Git.

To choose a new output directory:

```sh
backend/.venv/bin/python -m backend.sim.engine.demo --out backend/sim/runs/my-demo
```

To run an existing normalized scenario:

```sh
backend/.venv/bin/python -m backend.sim.engine.run backend/sim/contracts/scenario_a.example.json --out backend/sim/runs/example
```

The CLI and historical `run_engine()` wrapper use the same `run_simulation()` execution
path. `--mock` is retained solely for legacy analytic fixtures, is explicitly marked
in metadata, and is never used by the offline demonstration.

```python
from backend.sim.engine import run_simulation
from backend.sim.engine.demo import demo_scenario

result = run_simulation(demo_scenario())
print(result.arrival_at(53.535, -113.64, minute=180))
map_data = result.frames_at([0, 30, 60, 120, 240, 360])
grid = result.arrival_grid()  # immutable NumPy array
```

Tests (offline, including mocked provider retrieval):

```sh
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest backend/sim/tests -q -p no:cacheprovider
```

Benchmarks (use a new output directory on subsequent invocations):

```sh
backend/.venv/bin/python -m backend.sim.engine.benchmark --out backend/sim/runs/my-benchmarks
```

This runs 100/50/25 m single-member configurations and a 100 m five-member configuration
in fresh subprocesses. It records wall times, process peak RSS, dimensions, forecast
steps, horizon, and individual output file sizes in `benchmarks.json`.

See [HANDOFF.md](HANDOFF.md) for the complete input/output/query contract, FIFO proof,
revision semantics, limitations, and illustrative integration adapter. See
[VERIFICATION.md](VERIFICATION.md) for executed checks and measured results.
