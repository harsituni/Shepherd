# GET /route v3

The `/route` response the API serves (the only router; `contract.md`'s `/route`
section points here). How routes are built and judged: `backend/routing/README.md`.

Sample answers, generated from the real engine (`python -m backend.routing.tools.route_fixtures`):

| File | Situation |
| --- | --- |
| `fixtures/route_no_fire.json` | No fire running: 3 ok routes |
| `fixtures/route_mixed.json` | A fire cuts the usual road to one centre: it is shown `blocked` beside its `safest` detour |
| `fixtures/route_no_safe_route.json` | Standing inside the fire: every route `blocked`, `no_safe_route: true` |
| `fixtures/route_indeterminate.json` | Forecast does not cover the trips: every route `indeterminate`, nothing recommended |

## Request

`GET /route?lat=&lon=[&check_route_id=rt_...][&debug=1]`

Send `check_route_id` with the id of the route the person picked, on every poll.
That route stays in `options` even if it turns unsafe, so the phone can say so.

## Response (200)

Top level:

| Field | Meaning |
| --- | --- |
| `route_status` | `viable` (something is recommended), `blocked` (every route is cut by fire), `indeterminate` (nothing can be confirmed either way) |
| `best_route_id` | id of the recommended option, or `null` when `route_status` isn't `viable` |
| `no_safe_route` | `false` when viable, `true` when blocked, `null` when indeterminate |
| `leave_by_sim_min`, `leave_by_label` | departure deadline for the best route, or `null` |
| `options` | 2 to 4 routes, recommended one first, then in rank order |
| `forecast` | `{run_id, band, covers_until_sim_min, wind_kmh, wind_from_deg}`, or `null` with no fire |
| `forecast_error` | string if the fire forecast itself is unusable, else `null` |
| `excluded` | shelters with no road route: `{shelter_id, reason}` |
| `search` | `{complete, scope, shelters_evaluated}` |
| flat v2 fields | `shelter_id`, `shelter_name`, `distance_km`, `eta_min`, `geometry`, `steps`, ... copied from the best option; **absent** when there is no best |

Each option:

| Field | Meaning |
| --- | --- |
| `id` | `rt_<shelter_id>_<role>`, stable across polls; key the person's pick by this |
| `role` | `fastest`, `safest` (a detour around fire) or `alternative` |
| `status` | `ok` (≥ 60 min spare), `tight` (0 to 59), `blocked` (fire cuts it), `indeterminate` (can't confirm) |
| `margin_min` | spare minutes, `null` when no fire threatens it or when indeterminate |
| `reason` | one sentence for `blocked` / `indeterminate`, else `null` |
| `hazard_intercept` | where fire cuts a blocked route: `{lat, lon, road_name, fire_arrival_sim_min, closes_at_sim_min, driver_arrival_sim_min}` |
| `distance_km`, `eta_min`, `arrival_sim_min` | road travel only; `null` if the route's access is incomplete |
| `geometry` | LineString of the road travel (MultiLineString only for incomplete routes) |
| `access` | where the trip starts and ends, below |
| `shelter_threat_sim_min` | when fire reaches the centre itself, or `null` |
| `clear_until_sim_min`, `clear_until_label`, `steps`, `rerouted`, `reroute_reason`, `forecast_complete`, `warning` | as in v2 |

Only `ok` and `tight` options may be picked or recommended. `blocked` and
`indeterminate` options are shown greyed, never as navigation.

## Road-point endpoints

Trips run between road points. `access.origin` and `access.destination` each
have `point` (where the line starts or ends) and `unmodeled_m` (the distance
to the real place, which is not driven, timed or drawn):

- origin: `person_point` = the request pin, `person_access_verified: false`
- destination: `building_point` = the centre's coordinates, `building_access_verified: false`

A pin exactly on a road has no `person_point` / `unmodeled_m`. Show the gaps as
plain notes ("Join the road 58 m from you"), never as directions.

## Errors (404 `no_route`)

Only for: outside the demo area, no road within 300 m, or no open shelter
reachable by road. Every other situation, including "everything is blocked",
is a 200 with greyed options.

## Changes from v2

- `blocked`-only answers are now 200 with `no_safe_route: true` (was 404).
- New status `indeterminate`; `best_route_id` and flat fields can be absent.
- Option ids are stable and role-based; picks should be keyed by id, not shelter.
- No `margin_min: 999` sentinel; `null` means no threat.
- New fields: `route_status`, `no_safe_route`, `forecast`, `forecast_error`,
  `search`, and per option `role`, `hazard_intercept`, `access`,
  `shelter_threat_sim_min`, `geometry_scope`, `modeled_*`.
