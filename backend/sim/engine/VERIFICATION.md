# Executed verification — engine 0.2.0

## Test execution

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/routing backend/.venv/bin/python -m pytest backend -q -p no:cacheprovider
```

The full backend suite completed with **189 passed, 0 failed, no warnings**.
`PYTHONPATH=backend/routing` accommodates an existing legacy test's top-level
`from router import ...`; that routing file/test was not edited. All simulation tests
can also run independently without that environment variable using the README command.

The new tests cover independent FBP equation fixtures; wind reversal during a crossing;
increasing/decreasing speeds and multiple changes; analytic time-dependent arrivals;
zero/near-zero rates and resumed spreading; FIFO across all 16 directions; integration
convergence; deterministic results and byte-identical exports; forecast recomputation;
immutable buffers and concurrent readers; post-120-minute arrival semantics; closed
spatial boundaries including boundary ignition; geographic transforms and monotonic valid
GeoJSON; export/load integrity and overwrite refusal; ensemble seeding and unreached
quantiles; finite inputs, weather gaps/coverage, cache aliases, timeout retries and
malformed provider responses; and full offline weather-to-export execution with network
connections explicitly blocked. Existing calm/constant-wind and provider-fixture checks
also pass.

No new runtime dependencies were introduced. Existing dependency minimum versions were
made explicit, including Shapely >=2.1 for the coordinate-transform API already in use.

## Independent numerical comparison

Two 100 m cells, default M-1/PC50/FFMC92/BUI90, 180-minute horizon, 10 m/s wind FROM 90
at t=0 and t=60, reversing to FROM 270 at t=120 and remaining there at t=180.
The original algorithm reported the neighboring cell as unreached.

The independent reference uses scalar FBP equations, vector interpolation, bisection
for the ellipse/ray intersection, and midpoint distance marching at 0.002-minute steps.
It imports no production FBP, weather-interpolation or edge-inversion functions.
Reference arrival: **97.1202660249 minutes**.

| Integration step (min) | Engine arrival (min) | Absolute error (min) |
|---|---:|---:|
| 4 | 97.0199508667 | 0.1003151582 |
| 1 | 97.1138458252 | 0.0064201997 |
| 0.25 (default) | 97.1198654175 | 0.0004006074 |

The default error is about **0.024 seconds**, within the permanent regression tolerance
of 0.005 min. This checks numerical propagation; it does not measure real-world prediction
error. The six independent FBP fixtures use a separate 50-digit Decimal calculation of
published equations and compare to 1e-11 relative tolerance. Their source URLs,
coefficients and generator are in `../tests/fixtures/fbp_reference.json` and
`generate_fbp_reference.py`. They are equation checks, not observed-fire validation.

## Offline demonstration executed

```sh
backend/.venv/bin/python -m backend.sim.engine.demo
```

Produced `backend/sim/runs/offline-demo-r1/manifest.json`, both arrival arrays,
normalized scenario, grid header, metadata and **25 GeoJSON frames**. Actual FBP;
no OpenWeather key, server or network request. The input was the existing deterministic
`backend/sim/scenarios/edm-demo-1.weather.json` fixture, resampled through weatherpipe.

- Grid: **185 x 187**, 100 m; horizon: **360 min**; weather records: **7**.
- Reached cells: **1,342**.
- Ignition (53.535, -113.663): arrival 0, burned at t=180.
- East point (53.535, -113.64): arrival **113.0750198364 min**, burned at t=180.
- Far corner (53.421, -113.699): `not_reached` within 360 min.
- Outside (53.3, -113.5): `outside_domain`, burned=null.

The demo command chooses a fresh output directory on each invocation. The explicit
`--out` directory must not already contain a published result.

## Measured performance

Command:

```sh
backend/.venv/bin/python -m backend.sim.engine.benchmark --out backend/sim/runs/benchmarks-final
```

Each case used a fresh process on macOS arm64 / Python 3.14.7, six-hour horizon,
7 forecast records, 0.25-minute integration knots, and 25 output timestamps.
NumPy 2.5.4, pyproj 3.8.0, Shapely 2.2.0, rasterio 1.5.2, Pydantic 2.14.3.
These are single-run measurements, not statistical performance guarantees.
Peak RSS includes Python and native-library imports. Perimeter time is p50 only;
export time includes regenerating frames, hashing and writing all payloads, including
p10 frames when using five members. Process startup/import time is excluded from timings.

| Cell (m) | Grid | Members | Simulation (s) | Perimeters (s) | Export (s) | Peak RSS (MiB) | Output bytes |
|---|---|---|---|---|---|---|---|
| 100 | 185 x 187 | 1 | 0.0578 | 0.0217 | 0.0267 | 92.80 | 385,718 |
| 50 | 370 x 372 | 1 | 0.1078 | 0.0512 | 0.0629 | 97.70 | 1,310,564 |
| 25 | 739 x 743 | 1 | 0.3154 | 0.1763 | 0.1873 | 115.14 | 4,802,495 |
| 100 | 185 x 187 | 5 | 0.1555 | 0.0217 | 0.0531 | 98.67 | 524,403 |

Raw measurements, including every file's size, are in
`backend/sim/runs/benchmarks-final/benchmarks.json` (generated/ignored by Git).
At 25 m the two arrays are 2,196,436 bytes each and GeoJSON is 404,424 bytes.

Propagation work scales with reached cells and 16 edge inversions per cell; ensemble
cost scales with member count. Polygonization scans the grid for every requested frame,
and output arrays scale with domain area / cell size squared. Cumulative directional
tables remove repeated time integration from the inner loop. No additional optimization
or infrastructure was justified by these measurements. Larger fully burned domains and
large ensembles can cost substantially more than these cases.

## Scope and limitations

A Git diff check confirmed no edits to controller, API, routing, legacy wildfire simulator,
frontends or shared contract. Existing unrelated `.env.example` modifications were left
untouched. `git diff --check` passed.

No failing checks remain. True incremental continuation is deliberately unsupported;
revisions are deterministic full recomputations and preserve previously published results.
No empirical fire-growth calibration, terrain/fuel maps or operational safety guarantee
is claimed. The integration work remains deferred as specified; see HANDOFF.md.
