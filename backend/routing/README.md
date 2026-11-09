# Routing

`GET /route` answers with 2 to 4 road routes from the person's pin to open
shelters, each checked against the hazard forecast for the whole trip. The
response fields are in [`shared/route_v3.md`](../../shared/route_v3.md); this
file explains how the answer is made and what it does and doesn't claim. None of
it is a safety guarantee.

## Files

| File | What it does |
|---|---|
| `router.py` | Entry point: `load_graph()`, `find_routes()`, `prepare_forecast()`, `graph_bbox()`, `fire_closed_road_features()`, `NoRouteError` |
| `road_graph.py` | The road map as arrays (`RoadGraph`), compiled Dijkstra, nearest-node lookup, and the road-to-fire-cell table |
| `access.py` | Where a trip starts and ends on the roads (`JourneyGraph`), including part-way along a road |
| `safety.py` | Per-forecast road deadlines (`EdgeFire`) and `judge()`: ok / tight / blocked / indeterminate |
| `candidates.py` | Builds the routes: usual road, exact safe search, roomier `safest` detour, `alternative`s, and the straight-line backup |
| `select.py` | Ranking, the 80% overlap rule, and picking the 2 to 4 shown |
| `evac_zone.py` | The 1 km evacuation circles (same rule as the apps' `evacuation.js`) and which shelters they make unsafe |
| `traffic.py` | Evacuation traffic: BPR road delays, a simulated crowd plus real phones, anti-gridlock reassignment (`/traffic*`) |
| `evac_demand.py` | Estimates how many people and cars evacuate, from the pin, the local zone density and the Edmonton time of day |
| `tools/` | Map building (`import_osm`, `prepare_graph`), the speed benchmark (`bench_routes`), and the example-answer generator (`route_fixtures`) |
| `tests/` | Unit tests on tiny made-up roads (`helpers.py`), plus scenarios on the real Edmonton map and sim |

The sim side is `backend/sim/oracle.py`: `controller.oracle()` returns a frozen,
read-only `ForecastOracle` covering the whole road graph and at least the next
240 minutes. A request takes one snapshot and uses it throughout. The tornado
(beta) hands routing the same kind of oracle, so everything below applies to it.

## The road map

`load_graph()` runs once at API startup and never downloads. It reads
`SHEPHERD_GRAPH_PATH` if set, else `data/edmonton_demo_drive.graphml`, else the
shipped `data/edmonton_demo_drive.graphml.gz`, and binds the traffic engine to
it. If none loads (missing, unreadable, empty), the API still starts in
**backup mode**: options are straight lines marked `approximate`, nothing is
recommended, and the answer is `indeterminate`. Blocked or disconnected roads
never switch to backup.

The graph keeps every directed road, including parallel roads and loops, with
its own geometry, length and fire deadline. Free-flow travel is a fixed
30 km/h. Turn restrictions are not modelled. Roads tagged `access`, `vehicle`,
`motor_vehicle` or `motorcar` = `no`/`private` are not used. The demo area is
lon −113.75 to −113.32, lat 53.40 to 53.62.

## Where trips start and end

Both ends are points on mapped roads; the gaps to the real person and building
are reported as `unmodeled_m`, never driven, timed or drawn.

- **Start.** A pin on a road keeps that road (both directions if two-way). A
  pin on a crossing with no junction is ambiguous and indeterminate. Otherwise
  the trip starts at the nearest road point within 300 m whose roads lead onto
  the main network (the largest strongly connected part of the map, 98% of
  Edmonton's nodes); if no shelter is reachable from it, the next nearest is
  tried. No road within 300 m is a 404.
- **End.** Shelters with `routing_endpoint: "reachable_road_point"` (all eight)
  end at the nearest permitted road point reachable from the start, searching
  past 300 m if needed, chosen without looking at the fire. Every directed road
  through that point can be the last stretch, so a two-way street can be
  approached from either side. Shelters without it must have a mapped road
  within 300 m, or their routes stay indeterminate.

Partial roads are cut with Shapely linear referencing; each piece keeps its
original road's identity, so splitting doesn't make two routes look different.
Disconnected crossings, map gaps and wrong-way travel are never used as
shortcuts.

## Judging a route

The fire grid is 100 m cells. For each forecast, every road gets a deadline:
the earliest the fire reaches any cell it passes through, minus 30 minutes,
minus the travel time to leave that cell. `judge()` walks the trip in travel
order, from the person's own cell to the shelter's road point:

- **blocked**: a valid forecast shows the driver reaching a cell after its
  deadline (the first one is `hazard_intercept`). One proven conflict is enough,
  even if other cells are unknown.
- **indeterminate**: nothing proven, but some cell is unknown (outside the fire
  domain, NaN, past the forecast horizon) or the forecast doesn't reach 90
  minutes past arrival. No deadline or margin is given.
- **tight** / **ok**: every cell known and clear; under / at least 60 minutes
  to spare.

The route's departure deadline is the earliest of its fire deadlines, rounded
down; equality is allowed. With no fire on the route there is none. The forecast
window (`horizon − 90 − trip time`, the horizon capped at now + 240 minutes) only
limits the margin, so it can make a route `tight` or, once passed,
`indeterminate`, but it never sets leave-by: the window running out isn't a
reason to leave. A structurally broken forecast (`forecast_error`) makes every
route indeterminate. With no fire running the oracle is `None` and every route
is `ok` with no deadline.

The fire domain covers the whole road graph (`graph_bbox()`, set at startup) so
far roads aren't falsely clear. The domain edge is densified before projecting
to UTM so curved edges don't drop boundary cells.

**Leave-by.** `zone_check()` (`evac_zone.py`) finds the first minute the
evacuation circle, drawn around the forecast fire minute by minute
(`ForecastOracle.outlines`, the same ring the map shows), covers the pin. The
answer's leave-by is the earlier of 30 minutes before that and the route's own
deadline above. If the circle doesn't reach the pin within 4 hours the person is
not at risk (`at_risk: false`) and there is no leave-by.

**Evacuation zone.** After judging, `find_routes()` draws a 1 km circle around
the fire now and around each `/forecast` outline (`evac_zone.py`, the same rule
the dashboard and phone paint yellow). A shelter inside any circle has its
`ok`/`tight` routes turned `blocked` ("Fire is already near ..."); they stay
listed but are not recommended while a shelter outside the zone has a usable
route.

## Searching

1. Every eligible shelter (open, with space) gets its usual shortest road.
2. An exact safe search finds the earliest-arriving route that respects every
   road deadline: compiled Dijkstra, pruning roads whose start can't be reached
   in time, repeated until nothing changes. After 20 rounds it switches to an
   exact heap search over the original roads, so the answer is never cut short.
3. A roomier pass prefers roads with more spare time (`safest`); if its path
   judges blocked, the exact one is used. Penalty searches add `alternative`s.
4. Before saying "blocked", a search that relaxes only the unknown cells looks
   for a possible way through; if one exists the answer is indeterminate, not
   blocked.

Selection ranks ok routes by travel time (a shelter the fire reaches within two
hours of arrival ranks lower), then tight by spare minutes, then indeterminate,
then blocked. It drops a route that shares 80% of its road with a better one
(never the last usable one) and shows 2 to 4, from the three best shelters. The
route named in `check_route_id` is always rebuilt and kept. `search.complete`
means every eligible shelter was searched on the loaded graph; it says nothing
about the real world.

## Closed roads

`GET /roads/closed` (`fire_closed_road_features()`) lists the roads whose fire
deadline has already passed at the current sim minute, using the same `EdgeFire`
deadlines as `/route`. `count` is the full closed set; `features` keeps the 350
most overdue, preferring long and named roads so the dashboard's red layer reads
cleanly.

## Traffic

Off until `/sim/start`, which turns it on with a crowd sized by `evac_demand.py`
from the pin and the local time; `/sim/reset` turns it off. While it is on:

- Each road's travel time follows the BPR volume-delay formula
  (`1 + 0.15·(v/c)^4`, v/c capped at 3) from its lanes and road class. Every
  `/route` search uses those congested times, so jams can push a route from
  `ok` to `blocked`; options carry `traffic_delay_min` and `traffic_free_min`.
- Up to 2,500 simulated cars (each standing for a share of the projected crowd,
  up to 100,000) plus every phone heartbeat are loaded onto the roads. The
  crowd uses a plain Dijkstra to the shelters, not the full fire check.
- With anti-gridlock on, cars are reassigned every 2 sim minutes when another
  route saves at least a minute. `POST /traffic/compare` reports clearance time
  with and without it; `GET /route/traffic_hint` tells a phone when a faster
  route exists.

## Tools

From the repo root, with `backend/.venv` active:

```bash
python -m backend.routing.tools.bench_routes                              # in-process speed budgets
python -m backend.routing.tools.bench_routes --url http://localhost:8000  # replay against a running API
python -m backend.routing.tools.route_fixtures                            # regenerate shared/fixtures/route_*.json
python -m backend.routing.tools.prepare_graph                             # check the saved map offline
python -m backend.routing.tools.prepare_graph --download                  # download it if missing (Overpass)
python -m backend.routing.tools.import_osm --source <extract.osm.gz> --path <out.graphml>
```

`import_osm` converts a local BBBike OSM extract (driving roads only, one-way
directions kept) and never overwrites an existing file. It stops before
building the graph above 250,000 road nodes or 100 MB of filtered XML
(`--max-road-nodes`, `--max-xml-mb`); peak memory can still be several GB.
`prepare_graph` checks a map: node and edge counts, every demo shelter within
1 km of a road, and a route between every pair. `--download` uses the fixed demo
box and `SHEPHERD_OVERPASS_URL` if set; it never replaces an existing file.
Point the API at a new map with `SHEPHERD_GRAPH_PATH`. Everything in `data/`
except the shipped `.graphml.gz` is git-ignored.

## Tests

```bash
python -m pytest backend/routing
```

The unit tests use tiny made-up roads and hand-made forecasts and never touch
the network. `test_scenarios.py` and the API tests load the real Edmonton map
and run the real sim; they skip if the map isn't available.
