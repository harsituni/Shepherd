# Routing v3 feasibility search — F02, F04, F05, F10

This phase preserves the wildfire engine, oracle validity rules, cell-exit
safety calculation, 30-minute fire buffer, and 90-minute forecast reserve.
It changes which road paths and shelters are considered before reporting
feasibility. Routing v2 remains the default and retains its existing API.

## Representation and exact paths (F04)

`RoadGraph` retains every directed non-self-loop NetworkX `(u, v, key)` edge,
with its own geometry, length, road name, cell table entries, and fire deadline.
Self-loops cannot improve feasibility under nonnegative travel times and
deadlines that only close. OSMnx continues to load the saved `MultiDiGraph`;
the NetworkX graph itself is not modified.

For each compiled search, `shortest_paths()` builds a minimum-weight CSR matrix
over the currently allowed edges. This temporary reduction never sums parallel
weights or removes edges from the original graph. If a short road is rejected
by its deadline, a longer parallel road remains available in the next search.
The chosen original edge index for every matrix entry is retained and converted
to a predecessor-edge array. Reconstruction, final judging, distance, geometry,
and instructions all use those same exact edges, including in roomier and
penalty searches. Equal-cost parallel ties use the first stable edge index.

The older distance-only `edge_index()` / `path_edges()` helpers explicitly pick
the shortest-length road; hazard-aware production paths do not call them.
Explicit zero-time sparse entries are retained so search timing matches the
judge instead of accumulating artificial time at colocated junctions.

## Exact constrained feasibility (F10)

An edge may be entered at time `t` only when `t <= edge_deadline + EPS_MIN`,
using the judge's existing numerical tolerance. Travel duration is nonnegative.

The fast path still uses compiled SciPy Dijkstra and iterative pruning:

1. Find earliest arrivals using the allowed roads.
2. Remove every road whose start cannot be reached before its entry deadline.
3. Repeat until no further road is removed.

Each iteration's arrivals are lower bounds on feasible arrivals. Removing a
late edge cannot discard a feasible path: arriving later cannot make it usable.
At convergence, every predecessor edge satisfies its own constraint, and the
labels are exact earliest feasible arrivals.

After 20 compiled iterations, execution switches to a heap-based constrained
Dijkstra over all original edges. This is a performance switch, not a search
limit. It relaxes each individual edge only when the current earliest label
satisfies that edge's deadline. Earlier arrival dominates later arrival at
every node, so one label per node suffices and waiting/cycles cannot help.
The finite graph is searched to completion; no unconverged result is returned.
Worst-case fallback complexity is `O((V+E) log V)` in addition to the bounded
compiled work. A failed operation raises an error rather than fabricating a
complete negative answer.

The roomier and penalty passes remain heuristics for presentation. Their paths
are always judged, and an invalid roomier path falls back to the exact earliest
feasible path. Their optional search limits cannot erase that feasible witness.

## Shelters, diversity, and uncertainty (F02 / F05)

All open shelters with spare capacity are considered. Every shelter reachable
from the existing snapped origin gets its ordinary shortest route. There is no
five-shelter cutoff; the all-node searches already provide labels for farther
shelters. Closed, full, and road-unreachable shelters remain in `excluded`.

A viable detour is retained regardless of overlap/stretch relative to an
infeasible ordinary path. Display selection ranks viable options ahead of
indeterminate and blocked options before applying diversity. The 80% preference
may remove redundant viable options, but cannot remove the last viable witness.
The display remains limited to four options; path diversity is not exhaustive.

Before declaring blockage, another exact search relaxes unknown evidence while
retaining every known fire constraint. This optimistic search is used only to
detect possible indeterminate alternatives. Every resulting path is passed to
the unchanged judge, which still rejects missing coverage and expired forecasts.
Unknown data is never made evidence of viability. A blocked fastest path with
an unknown detour therefore yields an indeterminate overall result.

Completeness follows from earliest-arrival dominance under the existing journey
model: the initial connector is fixed, and destination-cell and forecast-expiry
checks only become harder with later arrival. If even the earliest optimistic
path is blocked by a known constraint, a later path cannot fix it. If it is
indeterminate, that uncertainty is retained. Destination-access travel remains
the separate unresolved F03 finding; this proof does not claim to cover it.

## API contract additions

V3 responses add:

```json
{
  "search": {
    "complete": true,
    "scope": "all_eligible_shelters_on_loaded_directed_graph",
    "shelters_evaluated": 6
  }
}
```

`complete` describes feasibility discovery within the named scope, not forecast
validity, exhaustive alternative enumeration, or real-world road accessibility.
`shelters_evaluated` counts eligible road-reachable shelters checked. In backup
mode the scope is `all_eligible_in_area_straight_line_estimates`; all such lines
are evaluated, and the existing `approximate` warning remains.

- A proven viable option gives `route_status: "viable"`, a `best_route_id`, and
  `no_safe_route: false` even if other routes have incomplete forecasts.
- `no_safe_route: true` requires a complete search and no unresolved path
  uncertainty within that scope; `route_status` is `"blocked"`.
- With no viable recommendation and an unknown path or incomplete search,
  `route_status` is `"indeterminate"` and `no_safe_route` is null. Incomplete
  search must never be inferred as blockage from the displayed options alone.
- Structurally invalid active forecasts do not trigger a constrained road
  search: `search.complete` is false and Phase 1's indeterminate response remains.
- `debug=1` adds `timings.exact_fallbacks`; `fixpoint_rounds` reports compiled
  iterations only, not an algorithmic completeness bound.

HTTP status rules and route IDs are unchanged. The shared contract and frontend
are intentionally not edited; downstream integration must adopt this search
metadata alongside Phase 1's nullable/indeterminate semantics.

## Library choices and verification

SciPy remains the compiled static shortest-path implementation. NetworkX stores
keyed topology and supplies exhaustive `all_simple_edge_paths` for the independent
small-graph reference. OSMnx handles graph loading, and Shapely still handles
road geometry; the independently checked raster-cell traversal is unchanged.

OSMnx's `to_digraph(weight=...)` and ordinary NetworkX multigraph shortest paths
reduce parallel edges by a static weight, so neither alone handles different
arrival-dependent edge eligibility or preserves the selected keyed geometry.
NetworkX's weight callback has no current arrival-label argument. Replacing the
compiled loops with these APIs would not solve the demonstrated defect. The
small exact heap fallback implements only the required entry-time predicate.

References: [SciPy Dijkstra](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html),
[NetworkX weighted search](https://networkx.org/documentation/stable/_modules/networkx/algorithms/shortest_paths/weighted.html),
[OSMnx conversion](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.convert.to_digraph).

`test_feasibility_v3.py` preserves the four original audit counterexamples,
compares 200 small directed multigraphs with exhaustive keyed-path enumeration
through both execution strategies, and compares complete candidate/selection
results with exhaustive paths under 60 synthetic hazard arrangements. The latter
deliberately reuses the existing safety judge while independently testing path
discovery. It includes unknown detours and exact buffer/zero-time cases.
Real-network tests verify every retained keyed edge against the loaded graph,
and compare all-node arrival labels with a separate heap reference before and
after an actual simulation wind reversal. Phase 1's full road-cell coverage tests
also run against the expanded parallel-edge representation.

Unresolved audit findings remain F03, F06, F07, F09, F11, and F12. Feasibility is
relative to the loaded graph, fixed speed, existing access points, and captured
forecast. It is not a claim about omitted shelter approaches, legal driving
restrictions absent from the data, traffic, physical connector access, selected
path identity, or controller lifecycle safety.
