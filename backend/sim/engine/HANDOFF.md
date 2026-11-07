# Standalone FBP engine: integration contract v1

Public execution is `backend.sim.engine.run_simulation(scenario)`. It is synchronous,
CPU-only, and does not fetch weather, write files, use HTTP, or access application state.
It returns a completed `SimulationResult`. Engine version: **0.2.0**.

```python
from backend.sim.engine import run_simulation, SimulationResult

result = run_simulation('backend/sim/runs/offline-demo-r1/scenario.json')
query = result.arrival_at(lat=53.535, lon=-113.64, minute=180, band='p50')
feature = result.perimeter_at(180)           # GeoJSON Feature
collection = result.frames_at([0, 30, 60, 120, 240, 360])  # FeatureCollection
arrival = result.arrival_grid('p50')         # read-only float32 NumPy array
metadata = result.metadata                 # detached dict, cheap relative to simulation
manifest = result.export('backend/sim/runs/my-new-export')
restored = SimulationResult.load('backend/sim/runs/my-new-export')
```

## Scenario input

Accepts a `Scenario`, dictionary, JSON string, string path, or `Path`. See
[`../contracts/scenario.schema.json`](../contracts/scenario.schema.json) for machine-readable
JSON Schema. Cross-field geographic/coverage constraints below are validated in Python.
Unknown fields, nonfinite numerical values and invalid geometry are rejected.

| Field | Contract / default |
|---|---|
| `schema` | Required literal `v1` |
| `scenario_id`, `run_id` | Required nonempty IDs; run ID restricted to letters, digits, dot, underscore, hyphen |
| `t0` | Required timezone-aware UTC timestamp |
| `horizon_min`, `step_min` | Required positive integer minutes; step <= horizon |
| `bbox` | Required `[west, south, east, north]`, EPSG:4326; closed geographic domain |
| `initial_perimeter` | GeoJSON Polygon or MultiPolygon **geometry**, valid and entirely within bbox |
| `ignition` | Alternative `{lat, lon}`; exactly one of ignition/perimeter required |
| `cell_m` | Positive integer grid resolution, default 100 m |
| `integration_step_min` | Maximum temporal knot spacing, default 0.25 min, range 0.001–60 |
| `weather` | Required strictly increasing entries, first `t_min=0`; fields below |
| `weather_end_policy` | `error` default rejects short series; explicit `hold` extrapolates last entry |
| `fbp` | `{fuel_type: 'M-1'|'M-2', pc: 50, ffmc: 92, bui: 90}`; defaults shown |
| `n_ensemble` | 1 by default, allowed 1–100 |
| `ensemble_seed` | Nonnegative integer, default 0, independent of run ID |
| `weather_source` | Optional JSON-compatible provenance dictionary, preserved |
| `execution_mode` | Only `recompute` supported |
| `revision_of` | Optional preceding run ID; descriptive lineage, not continuation |

Each weather entry contains `t_min` (integer), `wind_speed_ms` (0–60 m/s),
`wind_dir_deg` (0–360, meteorological FROM), `temp_c` (-60–60), `rh_pct` (0–100),
and `precip_mm` (nonnegative). Pipeline precipitation is a normalized hourly rate;
it is currently unused. Wind from 270 degrees favors spread eastward. Only the
engine converts m/s to km/h and FROM to spread bearing.

The implementation is restricted to **UTM zone 12N**: longitude -114..-108,
latitude 0..84. It rejects other regions. Maximum grid size is 2 million cells.
The domain is the geographic bbox, not the slightly larger snapped raster extent.
A point ignition seeds its containing cell; a perimeter seeds all touched cells.
This introduces a spatial error on the order of cell size, which is not a calibrated
conservative buffer. The weather pipeline currently builds perimeter scenarios;
the engine also accepts ignition-point scenarios directly.

## Numerical propagation and FIFO

1. Interpolate forecast wind as east/north vector components, including 0/360 crossings.
2. Evaluate fixed-fuel FBP rates at temporal knots, including forecast timestamps exactly.
3. Evaluate rates toward the 16 grid neighbors. Between knots, directional ROS is linear.
4. Integrate each direction once to obtain cumulative distance `C_theta(t)`.
5. A crossing of length `d` departing at `s` arrives at the earliest `t` satisfying
   `C_theta(t) = C_theta(s) + d`. Binary search finds the interval, and a stable
   quadratic root inverts its linear-rate integral. No near-zero rate cutoff is used.
6. Run label-setting Dijkstra over these time-dependent edges, seeded at time zero.

**FIFO justification:** nonnegative ROS makes `C` nondecreasing. If `s1 <= s2`,
then `C(s1)+d <= C(s2)+d`; the earliest generalized inverse is nondecreasing.
Thus an earlier departure cannot arrive later. Zero-rate plateaus implement waiting;
previously burning cells can contribute after favorable weather resumes. Earliest
arrival labels dominate later labels, which permits Dijkstra's settling rule.

Traversal is exact for the piecewise-linear directional rate approximation.
It is not an exact continuous-space fire solver. Refining the temporal knot spacing
reduces interpolation error; the 16-direction spatial stencil still has angular
bias. Internals use float64; final grids use float32 (about 0.00003 min rounding
scale at a six-hour horizon). The default reversal regression differs from an
independent midpoint-quadrature reference by about 0.000401 min (0.024 seconds).
This numerical error is much smaller than the model's physical/spatial uncertainty.

## Result and point-query semantics

`SimulationResult.grid` is a frozen grid description. `arrival_grid('p50'|'p10')`
returns an immutable bytes-backed NumPy array: even enabling its write flag fails.
Grid row zero is north; columns increase east. The origin is the **outer top-left**
corner. Cell center: `(origin_x + (col+.5)*cell_m, origin_y - (row+.5)*cell_m)`.
Lookup selects the containing cell; it does not interpolate arrival times.

`arrival_at(lat, lon, minute=None, band='p50')` returns a frozen `ArrivalQuery`:

| Field | Meaning |
|---|---|
| `status` | `arrival`, `not_reached`, `outside_domain`, `invalid_input`, or `unavailable` |
| `arrival_min` | Floating minutes since original t0 if known; otherwise null |
| `burned` | At requested minute: true/false when established; otherwise null |
| `query_min` | Requested minute or null; no implicit wall-clock/simulation clock |
| `horizon_min` | Complete modeled horizon; never a caller-imposed cutoff |
| `band` | Selected ensemble band |
| `row`, `col` | Raster indices if available |
| `message` | Explanation for unknown/invalid/domain outcomes |

Known arrivals survive queries before or after the arrival and beyond the horizon.
For a cell not reached by horizon H, `minute<=H` yields `burned=False` under this
model; `minute>H` yields `burned=None`. Outside-domain and unavailable predictions
always yield `burned=None`. None of these outcomes asserts operational safety.
Invalid input returns a structured status; an invalid scenario raises validation errors.

`perimeter_at(t)` accepts `0<=t<=H`, and rejects other/nonfinite times. It polygonizes
all cells with arrival <= t, retains holes/disconnected components, clips to bbox,
and returns valid EPSG:4326 MultiPolygon GeoJSON with `[lon, lat]` coordinates.
It does not simplify or round away burned regions. `frames_at(times)` returns a
FeatureCollection with the run ID; each feature has `properties.t_min` and `band`.
Frame dictionaries and metadata are detached copies. Concurrent reads are supported;
GDAL polygonization is serialized by a small lock. Reads never advance computation.

`metadata` contains schema/version, run/scenario IDs, normalized scenario SHA-256,
t0, recomputation/lineage, bbox and CRS, origin/shape/resolution, horizon/output step,
integration step, weather coverage/hold policy/provenance, FBP parameters, ensemble
seed/member perturbations/quantile method, seed/reached-cell counts, whether the fire
reached the domain boundary, and assumptions. Metadata is deterministic; timings are
measured separately by the benchmark CLI. `scenario` returns the normalized input.

## Export contract

`result.export(new_directory, minutes=None)` returns the manifest dictionary.
Default frames are 0, step, ..., horizon, with horizon included even if not divisible
by step. Exports contain:

| File | Format |
|---|---|
| `manifest.json` | `shepherd.engine.export/v1`, completion marker |
| `scenario.json` | Fully normalized input with reproducibility settings |
| `run_meta.json` | `shepherd.engine.result/v1`, metadata described above |
| `b1_header.json` | Existing B1 v1 header: CRS, origin, resolution, rows/cols, layer filenames |
| `arrival_p50.npy`, `arrival_p10.npy` | float32 NumPy grids; NaN means not reached within H |
| `frames.geojson` | FeatureCollection; p50 frames, plus p10 when ensemble has >1 member |

The manifest names `metadata`, `scenario`, `grid_header`, `frames`, and
`arrival_layers`; records `arrival_dtype`, `nodata`, `frame_minutes`, bbox,
CRSs, horizon, engine version and run ID; and inventories every payload file
in `files` with byte size and SHA-256. Grids are never embedded in JSON.

A manifest is published last. Readers must require it; partial failed exports are
not completed results. An exclusive export lock prevents concurrent writers. Existing
published directories are never overwritten. An existing matching `scenario.json`
from weatherpipe/build is permitted. Use a new directory for each revision.
`SimulationResult.load()` checks file hashes, grid dimensions and dtype, then exposes
the same immutable query interface. Existing B1 compatibility helpers remain;
`ArrivalGrid.arrival_min()` is a lossy legacy method and must not be used by new adapters.

## Forecast revisions and ensembles

Every run is **full recomputation from original t0/ignition**. Changed future weather
creates a new result; no existing result or exported run changes. New weather samples
can alter interpolated weather before their timestamp and can therefore alter earlier
predictions. Do not label this as continuation or observed history.

`weatherpipe.scenario.make_forecast_update` preserves original scenario geometry,
time and fixed parameters and records `revision_of`. Ensemble seed is unchanged,
so comparisons use the same perturbations even when run IDs change. `p10` and `p50`
are empirical inverse-CDF arrival quantiles, counting unreached members as infinity;
they are identical for one member. Small ensembles are sensitivity experiments,
not calibrated confidence bounds. No incremental continuation/checkpoint API is offered.
Future continuation must preserve burned history and partially traversed edges.

## Future application adapter (illustrative only)

```python
# Run outside the request path. An application chooses when/how to schedule this.
new_result = run_simulation(validated_scenario)
# Under the application's lock, publish this completed snapshot with its run ID.
active_result = new_result

# A request captures ONE snapshot and simulation time for its entire response.
r = active_result
now = simulation_minutes_since(r.metadata['t0'])
current_hazard = r.perimeter_at(now)   # only when 0 <= now <= r.horizon_min
forecast = r.frames_at(requested_absolute_minutes)
query = r.arrival_at(lat, lon, minute=now, band='p10')
# Handle status explicitly. Do not collapse unknown/outside into a safe route.
```

A separate integration task must modify these application components:

- `SimController`: replace legacy placeholder construction, maintain simulation clock
  separately, schedule full recomputations, publish snapshots, and expose run status.
- API: translate km/h controls into m/s scenario weather, preserve FROM direction,
  construct domain/ignition and fetch weather outside `run_simulation`. Current
  `fuel_dryness`/humidity mappings do not represent fixed FFMC/BUI.
- `/hazards` and `/forecast`: add the application contract's IDs, `kind`, `zone`,
  `source` and top-level `t_min` around engine GeoJSON. Agree whether display labels
  mean absolute t0 minutes or offsets from now. The engine always uses absolute t0 time.
- Frontends: accept MultiPolygon, explicit horizon/exhaustion states, revision IDs,
  and distinguish nominal p50 from optional earlier-arrival p10 bands.
- Routing: consume structured queries or raster arrays, sample every crossed raster
  cell/segment (or conservatively rasterize a buffered route), and account for travel
  time along the route. Start/midpoint/end sampling misses intervening fire cells.
  Outside-domain, exhausted-horizon and missing predictions require explicit policy.
  Flooring known arrivals may avoid upward time-rounding, but does not remove spatial
  approximation error. The 30-minute policy buffer remains outside this engine.

No controller, API, routing, legacy WildfireSim, or frontend changes are included.

## Physical limitations

Uniform M-1/M-2 fuel, fixed PC/FFMC/BUI, zero slope, instantaneous equilibrium spread,
uniform weather, no moisture recovery, explicit firebreaks or suppression are deliberate.
The model does not simulate fuel depletion or long-range spotting. Vector interpolation
between opposing winds can introduce an assumed calm interval. Grid convergence is
ignored. Raster seeding/resolution, fixed directional stencil and finite bbox affect
results. Reaching the bbox does not mean fire stops there in reality. These assumptions
are not an upper bound on actual fire behavior; no empirical calibration is claimed.
At BUI=0 the engine uses the zero-BUI limiting spread of zero; reference R's BUI<=0
sentinel convention (no buildup adjustment) is intentionally not adopted.
