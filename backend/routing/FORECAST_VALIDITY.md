# Routing v3 forecast validity and geographic coverage (F01 / F08)

These semantics apply to `find_routes_v3()` and `GET /route` with
the default routing (`SHEPHERD_ROUTING=v2` restores the old router). Routing v2's response semantics
are unchanged. The phone reads these statuses (see `shared/route_v3.md`).

## Route evidence and response contract

Every option has one of four statuses:

| `status` | Meaning | Eligible for `best_route_id` |
| --- | --- | --- |
| `ok` | Complete forecast coverage, required fire buffer satisfied, at least 60 whole minutes of departure margin | Yes |
| `tight` | Complete coverage and buffer satisfied, less than 60 whole minutes of departure margin | Yes |
| `blocked` | At least one valid modeled arrival proves a fire-buffer violation | No |
| `indeterminate` | No proven blockage, but invalid or missing coverage prevents establishing viability | No |

A known blockage takes precedence over unknown cells elsewhere or an expired
forecast: one demonstrated conflict is enough to reject that journey. Such an
option can have `status: "blocked"` and `forecast_complete: false`. Invalid
snapshot structure, however, prevents trusting any cell, so it is indeterminate.
Bad cell values elsewhere on the map do not invalidate a fully covered route.

Phase 2 extends these fields from the generated candidate set to an explicit
feasibility-search scope; see [FEASIBILITY.md](FEASIBILITY.md). The status rules are:

| `route_status` | `best_route_id` | `no_safe_route` |
| --- | --- | --- |
| `viable` | ID of a complete `ok`/`tight` option | `false` |
| `blocked` | `null` | `true` (complete search establishes blockage within its scope) |
| `indeterminate` | `null` | `null` (no viable recommendation, unknown path or incomplete search) |

Selecting an indeterminate route through `check_route_id` retains the option
for inspection but cannot promote it over a viable alternative. When there is
no recommendation, flattened recommended-route fields (including `geometry`)
are absent and top-level `leave_by_sim_min` / `leave_by_label` are null.
No geometrically feasible route still uses the existing HTTP 404 behavior.
An indeterminate result with candidate geometry is HTTP 200, not a server error.

Indeterminate options have `forecast_complete: false`, an explanatory `reason`,
and null `margin_min`, `leave_by_sim_min`, `clear_until_sim_min`, and
`hazard_intercept`. No fictitious fire interception is emitted for missing data.
A known shelter threat can still be reported. `forecast_complete` is a per-option
property; its flattened top-level copy exists only when there is a recommendation.

`forecast_error` is a string for structurally invalid oracle metadata, otherwise
null. With invalid metadata, `forecast` is null instead of serializing unusable
numbers. Individual cell/horizon failures use the option reason; they do not
erase otherwise valid forecast metadata. Responses remain strict JSON even
when the supplied oracle contains NaN or negative infinity.

The existing explicit idle convention is preserved: `controller.oracle()`
returns `None` only when no fire scenario is running. Idle routes are `ok` with
no forecast, margin, or deadline. `None` must not be used to represent a failed
active forecast; that is not evidence of a fire-free scenario.

## Validity and time limits

The oracle must have finite numeric time, horizon, wind, and grid metadata;
nonnegative time/horizon and valid wind; positive grid dimensions, version and
cell size; the supported UTM CRS; a supported band and run ID; and correctly
shaped numeric arrivals and boolean domain mask within the engine's grid limit.
Invalid structure produces indeterminate routes before projection/indexing.

For an in-domain cell:

- A finite arrival in `[0, covers_until_sim_min]` is modeled fire arrival.
- Positive infinity means the engine modeled the cell and did not reach it by
  that finite horizon. It is evidence only within that horizon.
- NaN, negative infinity, negative finite arrivals, and arrivals beyond the
  declared horizon are unknown.
- Off-grid indices and false domain-mask entries are always unknown, regardless
  of the stored arrival value. Unknown edge entries cannot enter safe search.

All times are absolute simulation minutes from scenario ignition. Let `t` be
departure, `tau_i` travel time to the exit of cell `i`, `T` total modeled travel
time, `A_i` a valid finite fire arrival, and `H` the forecast horizon. Viability
requires all visited cells (including initial connector and destination checks)
to be known, and both:

```
t + tau_i + 30 <= A_i    for every finite modeled arrival on the journey
t + T + 90 <= H         existing forecast-coverage reserve
```

Equality is allowed, with the existing `1e-6` minute floating-point tolerance.
The fire buffer is still 30 minutes; the separate 90-minute completeness reserve
is now enforced, not merely reported as an advisory flag. For a complete active
forecast the absolute departure limit is:

```
min(min_i(A_i - 30 - tau_i), H - 90 - T)
```

`leave_by_sim_min` rounds that limit down to a whole simulation minute.
`margin_min` rounds down the remaining time to that limit, so it now includes
forecast expiry as well as fire arrival. A valid all-positive-infinity route
has a finite coverage deadline. Example: a four-minute trip with `H=100` can
depart through `T+6`; at `T+7` it is indeterminate unless a known fire conflict
already establishes blockage. Incomplete routes have no departure deadline.
A complete blocked route can retain its already-missed deadline and intercept.

The existing `clear_until_sim_min` describes buffered fire presence on the
route, not a departure guarantee; when present it is also capped by `H-90`.
Coverage-limited tight routes explain forecast expiry without inventing an
intercept. Forecast-based deadlines remain conditional on this scenario's
assumptions and subsequent updates.

## Geographic coverage

The geographic bbox is a longitude/latitude rectangle. Its sides become curves
in UTM; joining only its four projected corners excluded valid boundary cells,
including 66 Street SW at `(lat=53.395873, lon=-113.442712)`.

`projected_domain()` densifies those geographic sides at 0.001 degree intervals
before projection. Grid bounds, engine burnable cells, and the oracle domain
mask use that same polygon. The mask uses closed-cell square intersections,
matching road-cell traversal semantics. GDAL `all_touched` was also observed
to miss thin boundary intersections depending on boundary subdivision; it is
no longer used for the domain mask. Ignition rasterization is unchanged.

The domain is modeled at whole-cell resolution: a boundary cell is modeled if
its closed square intersects the polygon. It is not a subcell geographic fence.
Projection densification is a numerical approximation; the regression compares
the entire mask against a 10x finer boundary, including the observed slivers.
Every entry in the shipped graph's road-cell table is checked against the
domain for three ignition locations. Remaining uncovered/invalid entries are
flagged and rejected as evidence of safety even for other/custom grids.

The spread equations, directional rates, time integration, and travel-speed
model are unchanged. Common-interior arrival values are checked for equality
when expanding the simulation domain. The domain-mask correction is shared by
both simulation consumers; Routing v2's algorithms and feature flag are untouched.

## Verification and scope

Regressions are in `backend/routing/test_forecast_validity.py`,
`backend/api/test_forecast_coverage.py`, and
`backend/sim/tests/test_domain_coverage.py`. They cover synthetic invalid inputs,
expiry and delayed departures, independent deadline arithmetic, preservation
of valid and blocked routes, selection, full road-cell coverage, and the actual
ASGI API fire/origin reproduction. API corruption cases deliberately replace
an actual snapshot and are distinguished from the unmodified simulation case.

Future frontend contract work must accept the new status, nullable
`no_safe_route`, absent recommendation fields, `forecast_error`, and expiry-limited
deadlines/margins. It must never turn null into a safety claim.

This document covers F01 and F08; F02/F04/F05/F10 are covered by the subsequent
[feasibility remediation](FEASIBILITY.md). Destination approach modeling,
snapshot immutability hardening, and route identity remain unresolved. These changes establish
forecast validity for the journey the current engine evaluates; they do not
certify complete real-world evacuation safety.
