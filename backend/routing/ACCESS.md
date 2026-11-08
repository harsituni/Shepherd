# Routing v3 geographic access (F03/F11)

Routing v3 models a complete journey only when its start and end lie on
continuous, permitted, directed road geometry. Proximity alone does not
establish a traversable connection. The shipped drive map contains no building
entrance paths, barrier polygons, or verified off-road access network, and none
of the eight configured shelter points is on that road geometry.

For the demo, both ends of a journey are therefore road points (see
[Demo simplification](#demo-simplification-road-point-endpoints)): the person's
nearest reachable road point and each centre's designated road point. The gaps to
the person and to the building are reported, never driven, drawn or timed.
Shelter coordinates and identities are kept as metadata, never relocated. A
shelter without `routing_endpoint` keeps the strict rules below.

## Geographic algorithm

- Project to the same EPSG:32612 metres used by the simulation and road-cell table.
- Query a Shapely STRtree, then measure exact point-to-polyline distance. The
  origin's 300 m threshold applies to edges, including long edges and loops.
- A 1 mm tolerance accommodates coordinate round-off only; it is not an allowance
  for driving across an off-road gap. An on-road pin uses its mapped corridor(s).
  Otherwise all permitted candidate edges within 300 m remain unverified.
- A destination without candidates within 300 m gets nearest-road diagnostic
  candidates with unverified access, even when its missing approach is longer.
  No straight connection is created, traversed, timed, or drawn across that gap.
- Explicit `no`/`private` access, vehicle, motor_vehicle, or motorcar tags exclude
  an edge from v3 travel. Missing restrictions inherit the drive graph's modeled
  access assumptions. This is map evidence, not field verification.
- Geometric crossings on distinct corridors without a graph junction are
  ambiguous. NetworkX connected components distinguish a common junction from
  disconnected colocated roads. Ambiguous access is unverified, not a transfer.
- A request-local graph adds origin suffixes and destination prefixes using
  Shapely linear referencing and `substring`. Same-edge journeys get a directed
  clipped arc. A journey cannot travel backward along a one-way edge.
- Every arc retains its original keyed-edge identity and fractional interval.
  Parallel geometries stay distinct. Self-loops remain available for interior
  access. Overlap compares intervals on original keyed roads, so splitting does
  not manufacture diversity. Neither the shared road graph nor oracle changes.
- Geometry endpoints must meet their graph nodes. Gaps are excluded from verified
  search and remain explicit in diagnostic paths; output uses MultiLineString
  rather than drawing fictitious chords across disconnected portions.

OSMnx continues to load the saved drive graph. Its single-nearest-edge operation
alone cannot establish access, ambiguity, all directed candidates, or partial
journeys. Shapely supplies the index, projection, clipping, and geometry checks;
NetworkX supplies the small crossing-component check. Existing SciPy searches
and the exact constrained heap fallback remain unchanged. No dependencies added.

## Complete-journey safety

Partial-edge distance is the original OSM edge length times the traversed
geometric fraction. Travel speed remains 500 m/min. Cached fire-cell intervals
are clipped to exactly that portion, with entry/exit distances relative to its
new start. Zero-duration edges use spatial clipping directly because their
scaled cached distances cannot identify a geometric fraction.

The existing judge then checks the actual origin point, all partial/full road
arcs in cumulative travel order, and the actual destination point. The final
approach is included exactly like any other modeled road portion. The 30-minute
fire buffer and 90-minute forecast reserve are unchanged. Unknown access or
forecast coverage cannot produce a viable route or departure deadline. A known
conflict on a modeled portion can still establish blockage: omitted access time
could only make arrival later under the fixed-speed model.

Strict feasibility search excludes unverified arcs. The optimistic diagnostic
search retains known fire constraints but relaxes unknown access/forecast
constraints; its final judgment remains indeterminate. Thus a blocked shortest
path does not hide a verified or unknown alternative. The all-shelter exact
search and Phase 2 keyed path reconstruction are retained.

`search.complete` refers to the defined candidate graph, not universal physical
accessibility: mapped corridors for on-road points, candidate origins within
300 m otherwise, and destination candidates as above. Disconnected or
wrong-direction mapped endpoints still return the existing no-road-route 404.
No-road-within-300-m is now measured to permitted edge geometry. Routing v2's
nearest-node behavior and response are unchanged.

## API implications (frontend not changed)

Every v3 option adds:

- `access`: origin/destination records with `status` (`mapped` or `unverified`),
  actual `point`, projected `road_point`, `gap_m`, and `reason`; plus
  `geometry_continuous` and `complete`.
- `geometry_scope`: `complete_journey` or `modeled_road_portions`.
- `modeled_distance_km`, `modeled_duration_min`: only the represented road travel;
  for an incomplete journey these are lower-bound travel quantities, not ETAs.
- `arrival_sim_min`: full modeled arrival time only when access is complete.

For incomplete access, `distance_km`, `eta_min`, `arrival_sim_min`, `connector_m`,
and departure deadlines are null. Geometry contains only represented roads:
LineString, or MultiLineString for separated portions. The actual endpoints are
retained in access metadata; geometry is not falsely extended to them. A missing
road graph returns diagnostic options with null geometry and incomplete search;
it cannot recommend a straight-line route. In that fallback `access` contains
`complete: false` and a reason instead of projected endpoint records.

A hazard intercept adds `driver_arrival_is_lower_bound` when missing access time
prevents a full arrival estimate. Known blocked routes remain blocked, even if
access is incomplete. `forecast_complete` means evidence covers the entire
journey; it is false when a journey itself is incomplete.

Only complete `ok`/`tight` options can become `best_route_id`. If no option is
viable and some are indeterminate, `no_safe_route` remains null; true is reserved
for established blockage within the declared search. Existing clients must
handle null totals and inspect geometry/access scope before showing navigation.

## Demo simplification: road-point endpoints

Both ends of a modeled journey are points on mapped road geometry. Nothing
between those points and the actual person or building is modeled.

- **End.** A shelter with `routing_endpoint: "reachable_road_point"` (all eight
  configured centres) ends at the nearest point on a permitted road that is
  reachable from the start, searching outward past 300 m if needed. Every
  directed road through that point is a possible final arc, so a two-way street
  can be approached from either side.
- **Start.** A pin on mapped road geometry keeps its corridor(s), and a pin on a
  crossing without a junction stays ambiguous (indeterminate), as before.
  Otherwise the journey starts at the nearest road point within 300 m whose
  roads lead onto the main road network: the largest strongly connected part of
  the permitted, geometrically continuous map (98% of Edmonton's nodes). Every
  directed road through that point is a possible first arc. If no shelter is
  reachable from it (for example, a one-way road leading away), the next-nearest
  point is tried. Beyond 300 m the existing 404 applies.
- **Not modeled.** The gap to the person or building is not driven, timed,
  drawn, or checked cell by cell. `distance_km`, `eta_min`, `arrival_sim_min`
  and departure deadlines cover road travel only; `connector_m` is 0.
- **Still judged.** The whole modeled journey, cell by cell in travel order,
  including both road points, with the unchanged 30-minute buffer and 90-minute
  forecast reserve. The person's own cell is also judged at departure (zero
  distance, no added time): a known fire where they stand blocks every route,
  and unknown forecast there makes routes indeterminate. The building's cell is
  outside the journey. `shelter_threat_sim_min` still reports it.

Keyed multigraph routing, edge snapping, exact feasibility search, forecast
validity and hazard evaluation are unchanged. The sim, frontend, dashboard and
shared contract are not modified.

### API implications

On each option, both `access.origin` and `access.destination` now have
`status: "mapped"`, `kind: "designated_road_point"`, `gap_m: 0`, and `point` =
`road_point` = where the modeled journey starts or ends. The real locations are
separate:

| Field | Origin | Destination |
| --- | --- | --- |
| actual location | `person_point` (the request pin) | `building_point` (the centre's coordinates) |
| access verified | `person_access_verified: false` | `building_access_verified: false` |
| unmodeled gap | `unmodeled_m` (person to road point, ≤ 300) | `unmodeled_m` (road point to building) |

`geometry` runs from `access.origin.point` to `access.destination.point`. Neither
gap is drawn. `access.complete` and `geometry_scope: "complete_journey"` describe
the modeled road-point journey, not arrival at the building. Clients should
show the walk to the road and from the road to the building as unmodeled, for
example "Join the road 58 m from you" and "Centre entrance is 31 m from the
road point", and must not present them as navigation. An on-road pin has no
`kind`, `person_point` or `unmodeled_m` on its origin (unchanged). `GET
/shelters` features carry `routing_endpoint` in `properties`.

### Results (2026-11-08)

With the actual eight centres and actual off-road pins, every request was
indeterminate before this change, even with no fire. After it, seven Edmonton
pins (gaps 1–94 m) are viable with no fire. With a fire (53.535, −113.663,
35 km/h from 270°), six are viable (two of them tight), and the pin inside the
fire is blocked. In-process, 140 requests with a fire, same machine and run:
mean 89.3 ms / p95 101.7 ms now, versus 90.9 / 103.4 ms with only the start
rule switched back to strict. The start step costs 0.8 ms per request, plus a
one-off 4 ms network check per loaded graph. About 53 ms of each request is the
per-request journey-graph and destination search from Phase 3, so the
mean-under-100 ms budget now has little room.

## Verification

`test_access_v3.py` includes the original missing 1 km shelter approach, a mapped
hazardous approach, long-edge midpoints, isolated nodes, one-way reversal,
unknown origin gaps, exact 300 m boundaries, inaccessible roads, bridge crossings,
geometry gaps, loops, invalid coordinates, partial-edge hazards, zero-duration
partial arcs, buffer equality and forecast reserve. An independent reference
exhaustively enumerates keyed paths and intersects raster squares with Shapely
instead of calling the route judge or its cell-traversal algorithm.

Live simulation tests reproduce Township Road 514 and the 66 Street SW API case,
verify all road-cell entries, and retain the previous fire/ranking regressions
using explicitly declared road meeting points. Separate tests require the actual
unmoved shelter coordinates to remain unverified. Unit safety fixtures declare
modeled access explicitly so access uncertainty cannot mask forecast regressions.

References: [Shapely STRtree](https://shapely.readthedocs.io/en/stable/strtree.html),
[linear referencing and substring](https://shapely.readthedocs.io/en/stable/manual.html#substring),
[OSMnx nearest_edges](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.distance.nearest_edges).

## Local verification results (2026-11-08)

Python 3.14.7: complete backend suite, 465 tests and 22 subtests passed. The new
access file contributes 22 tests; real-road scenarios add two further access
regressions. Existing Phase 1 invalid/short/unknown forecast tests still isolate
forecast behavior with explicitly mapped endpoints. No simulation or oracle
implementation files changed in Phase 3; Routing v2 tests remain passing.

Same local 20-minute replay, seven pins, 140 in-process requests:

| Measurement | Before | After |
| --- | ---: | ---: |
| Graph load including array preparation | 2.27 s | 2.60 s |
| Array/index preparation, median of three separate builds | 339.20 ms | 681.38 ms |
| Road-cell table | 185.53 ms | 278.78 ms |
| Forecast deadlines, slowest of five builds | 2.38 ms | 2.43 ms |
| Request mean | 18.31 ms | 76.46 ms |
| Request p95 | 30.52 ms | 91.77 ms |

Directed edge access lookup averaged 0.17 ms over 2,000 random pins. All existing
benchmark budgets passed; compiled feasibility iterations peaked at four, with
no fallback required in this replay. The new graph includes 568 loop edges
previously omitted (53,270 total edges). The request now constructs and checks
partial-access graphs and may search both verified and indeterminate paths.
These are local in-process measurements, not an HTTP/concurrency benchmark or
an operational latency guarantee.
