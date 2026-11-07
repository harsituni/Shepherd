# Road routing and straight-line backup

This prototype chooses the shortest reachable road route to an open shelter
with spare capacity. Roads crossing core hazards are removed before routing.
If the saved graph cannot load, it returns a straight-line estimate to the
nearest eligible shelter whose line does not touch a core hazard. Neither
mode establishes that a route is safe or currently drivable.

`load_graph()` never downloads roads. It uses `data/edmonton_demo_drive.graphml`
by default, or `SHEPHERD_GRAPH_PATH` if set. Missing, unreadable, malformed, or
empty road graphs activate backup mode and log a warning instead of stopping
backend startup. A loaded graph with blocked or disconnected roads still
raises `NoRouteError`; it never switches to a straight line.

Backup responses retain the existing single-route fields and add
`approximate: true` and `warning`. Distance is straight-line distance; ETA is
only illustrative at 30 km/h. `steps` is empty and these are not navigation
instructions. Lines touching core hazards, including either endpoint, are
rejected. Closed/full shelters and locations outside the demo area are excluded.

The API passes these extra fields through, but the phone does not yet display
the warning or distinguish backup estimates from driving routes. Inspect the
JSON/backend log; do not present the phone's backup line as a driving route.

## Merged v2 interface

`find_route(lat, lon, hazards, shelters)` still handles core polygons and road
detours exactly as before. The updated API calls `find_routes()` and
`check_route()` instead. Both accept the simulation's `arrival_min` callback
and optional `sim_time`, and return v2 options plus the old flat fields.

Each eligible shelter gets the shortest road path that meets the known fire
deadlines. The search visits the earliest reachable nodes first and skips roads
where the driver would arrive after `fire arrival - 30 minutes`. If the usual
path is blocked, it searches other roads, including parallel roads, without
changing the saved graph. One-way directions are respected.

Driver arrival is `sim_time + cumulative road length / speed`, using the same
illustrative 30 km/h speed as before. Each road uses its saved length; its travel
time is spread along its geometry. Only the displayed ETA is rounded up.
Equality with the 30-minute deadline is allowed. Earlier arrival at a node is
always at least as useful as later arrival under these fixed fire deadlines,
so the search only needs to remember the earliest arrival at each node.

Up to three options are returned. Forecast checks sample road bends and points
at most 50 metres apart. The callback supplies all fire arrival times; routing
subtracts the contract's buffer and cumulative travel time for leave-by/margin.
Blocked options are excluded from selection. With no usable options,
`NoRouteError` is raised; blocked roads never activate straight-line backup.

Route IDs use the shelter ID (`rt_sh_kinsmen`, for example), so closing another
shelter does not change the meaning of a selected ID. `check_route()` recalculates
the path to that shelter and updates both the flat fields and selected timing.
It does not remember an old road path.

Missing fire arrival values do not establish safety. `forecast_complete: false`
and a warning identify missing predictions, including partly known routes.
These routes remain eligible for this simulation, but are not verified safe.
Any numeric margin or deadline covers only the samples with known predictions.
`forecast_complete: true` only means every sampled point returned a time, not
that the route is safe. If every sampled value is
`None`, margin and leave-by are `null`, rather than main's artificial `999` minute
margin. The option retains `status: "ok"` to mean no sampled forecast conflict,
with an explicit unknown-timing label and warning. This is a contract limitation:
v2 has no unknown status and its numeric margin rules do not cover this case.
The team must agree how to display unknown timing. The phone still assumes a
null leave-by means no fire for two hours; routing cannot establish that claim.

Remaining integration limits:

- The API supplies no core hazard polygons to the v2 calls. Dashboard-dropped
  hazards are therefore not checked by `/route`. Exact polygon avoidance is
  preserved in `find_route()`, but needs API wiring for v2.
- Forecast sampling can miss small hazards between samples. Snapped road
  endpoints do not model travel from the user's position or into a building.
- Travel speed is fixed; traffic and turn restrictions are not modeled. The
  search has only been tested on tiny offline graphs here, not benchmarked on
  the full Edmonton graph. A forecast callback must stay consistent during a
  request and return absolute simulation minutes, not minutes from now.
- Backup v2 options are marked `approximate: true` at both option and response
  level. Their timing is also only an estimate, not navigation instructions.

The simulation is a prototype. None of these outputs guarantees safety.

Call `load_graph()` once at startup. The selected mode lasts until restart.
Calling `find_route()` before startup still raises an error. The routing
Python dependencies must be installed even when using backup mode.

## Try backup mode without touching the real graph

From the repository root, point a fresh demo process at a nonexistent file:

```powershell
$env:SHEPHERD_GRAPH_PATH = "backend/routing/data/missing_backup_test.graphml"
backend/routing/.venv/Scripts/python.exe -B backend/routing/demo.py
Remove-Item Env:SHEPHERD_GRAPH_PATH
```

No file is created or deleted. Look for `"approximate": true` and the warning
in the output. Clearing the environment variable restores the default saved
graph for the next process. If you normally use a custom path, set it back
instead. Importing/downloading roads remains a separate manual step below.

## Setup

Use the **shared** backend venv (same as the API). From the repository root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate          # Windows: backend\.venv\Scripts\activate
pip install -r backend/requirements.txt
```

`backend/requirements.txt` already includes `osmnx`, `networkx`, and `scikit-learn`.
`./dev.sh` / `./demo.sh` install that file automatically if imports are missing.

OSMnx installs Shapely as a dependency. Scikit-learn supports nearest-node
lookups on the unprojected longitude/latitude graph.

## Offline tests

```bash
source backend/.venv/bin/activate
python -B -m unittest discover -s backend/routing -v
```

The tests use tiny NetworkX/XML fixtures, real OSMnx nearest-node lookups,
and temporary GraphML files. Download calls are mocked or blocked. They do
not load the large Edmonton graph. No internet is needed once packages are installed.

## Real Edmonton demo (run separately)

### Import the BBBike extract offline

The local file is `data/planet_-113.700,53.420_-113.430,53.580.osm.gz`
(about 44 MB compressed). The large import has not been run by the coding agent.

Close unused apps and stop running backend processes first. Open Task Manager
to watch memory. From the repository root, run only one conversion:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.import_osm
```

The script selects the single `.osm.gz` file in `data/`. If there are several,
choose the source explicitly:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.import_osm --source "backend/routing/data/planet_-113.700,53.420_-113.430,53.580.osm.gz"
```

It reads the compressed file twice, keeping only driving ways and their nodes.
It writes a smaller temporary XML file before OSMnx builds the graph. Buildings,
footpaths, bicycle-only paths, service roads, and roads marked as inaccessible
to cars are excluded. The road allowlist is deliberately conservative; it may
exclude roads with unusual tags or access exceptions. OSMnx preserves standard
one-way directions and calculates lengths before simplifying road geometry.
Turn restrictions and conditional access rules are not modeled.

The original `.osm.gz` is read only. No Overpass calls are made. Temporary files
are placed under the output folder and cleaned up on normal completion or
Ctrl+C. Filtering stops above 250,000 road nodes or 100 MB of filtered XML.
These guards reduce risk but are not a RAM limit: OSMnx still builds the graph
in memory, and compressed size does not predict peak memory use. Stop with
Ctrl+C if memory climbs too high; do not wait for the computer to freeze.
If a guard stops the import, use a smaller extract rather than raising it blindly.

The output is `data/edmonton_demo_drive.graphml`. An existing output is never
overwritten: check it with `prepare_graph`, or choose a new name with `--path`.
The graph is saved before the existing four-location checks run. If validation
fails, the error identifies the saved file so it can be inspected offline.
Only use it for the full demo after those checks pass. Data and temporary files
under `data/` are already ignored by Git.

After a successful import, select the graph before starting the backend:

```powershell
$env:SHEPHERD_GRAPH_PATH = "backend/routing/data/edmonton_demo_drive.graphml"
```

To repeat validation without converting or downloading:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.prepare_graph
```

### Prepare the larger graph manually

From the repository root, explicitly allow the preparation script to download:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.prepare_graph --download
```

This uses the fixed demo box `(-113.70, 53.42, -113.43, 53.58)` and saves
`backend/routing/data/edmonton_demo_drive.graphml`. Existing files are checked
and reused, never replaced, even with `--download`. The downtown graph is kept.
An invalid existing file fails the check instead of triggering a download.

To use a different Overpass server, set `SHEPHERD_OVERPASS_URL` before running
the download command. Use the server's API base URL, not its `/interpreter`
endpoint. If the variable is unset, the current OSMnx default is kept.
This setting only applies when downloading; saved-file checks stay offline.

OSMnx splits the request area into pieces of at most 25 square kilometres,
keeps server rate limiting enabled, and caches responses in `data/http_cache`.
It assembles the roads before simplifying them, avoiding manual tile joins.
Requests use a 120-second timeout, but server waits and retries can make the
whole run much longer. This is not a total runtime or memory limit. Expect
multiple requests and more memory use than downtown; Ctrl+C stops the process.
Rerunning reuses completed cached responses. After downloading, the graph is
saved before validation. Failed checks report the error and keep the saved
file for offline inspection; rerunning checks that file without downloading.
The existing `data/` Git ignore rule excludes the output and response cache.

Check the expanded file again without allowing any download:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.prepare_graph
```

Check another file offline with `--path`, for example:

```powershell
backend/routing/.venv/Scripts/python.exe -B -m backend.routing.prepare_graph --path backend/routing/data/downtown_drive.graphml
```

Checks print node/edge counts, distance to the nearest road node for each of
the four locations, and road distances for all 12 directed location pairs.
Every location must lie inside the node bounds and within 1,000 metres of a
road node; every pair must have a positive-length route. Failures exit nonzero.
This is a baseline connectivity check without hazards, not proof of complete
map coverage, building access, or safe evacuation. The 1,000-metre tolerance
is a demo sanity check, not a real access-distance guarantee. Routes that need
roads outside the demo box may be missing. Test wildfire detours separately.

Select the expanded graph before starting the backend:

```powershell
$env:SHEPHERD_GRAPH_PATH = "backend/routing/data/edmonton_demo_drive.graphml"
```

The saved downtown graph has 501 nodes and 842 edges, and does not cover all
four locations. The local `downtown.osm` also covers only a small downtown area.
No larger graph was downloaded as part of adding this script.

### Run the route demo

```powershell
backend/routing/.venv/Scripts/python.exe -B backend/routing/demo.py
```

The demo uses the contract's approximate shelter locations and fictional
availability. Its user is at latitude 53.520, longitude -113.620.
It prints the selected shelter, road distance, illustrative ETA, and GeoJSON.

To use an existing GraphML file, set this before starting the backend or demo:

```powershell
$env:SHEPHERD_GRAPH_PATH = "backend/routing/data/downtown_drive.graphml"
```

Relative paths are resolved from the current working directory. Missing or
unloadable files select estimate-only backup mode without contacting Overpass.
Set the variable before the first `load_graph()` call; later calls reuse the mode.
The default graph is `backend/routing/data/edmonton_demo_drive.graphml`.
The demo area is longitude -113.70 to -113.43 and latitude 53.42 to 53.58.
The data, cache, and virtual environment are ignored by the routing .gitignore.
The preparation scripts still report import/download failures to the caller.

## What each function does

- `NoRouteError`: signals that no eligible shelter is reachable in the demo graph.
- `load_graph()`: reads saved roads, or enables estimate-only backup mode.
  Call it once at backend startup before calling `find_route()`.
- `_inside_demo()`: prevents locations outside this demo area from snapping to
  unrelated boundary roads.
- `_shortest_edge()`: chooses the shortest connecting road when two nodes have
  more than one road between them, matching NetworkX's length weighting.
- `_route_details()`: adds edge lengths and joins their coordinates. It reverses
  stored geometry when needed to match travel direction. If an edge has no
  geometry, it uses that edge's endpoints.
- `find_route()`: snaps the user and each eligible shelter to nearby nodes,
  searches directed roads by length, skips unreachable shelters, and returns
  the shortest result using the existing response fields. In backup mode it
  uses `_straight_line_route()` and adds estimate metadata.
- `closed_roads()`: still returns an empty list as a Step 2 placeholder.
- `demo.main()`: loads the roads and prints a route using three sample shelters.

## Response details and limits

Coordinates use `[longitude, latitude]`. In road mode, distance is the sum of selected road
edge lengths, converted from metres to kilometres. Routes begin and end at
snapped road nodes, not exact user coordinates or building entrances. Access
from a building to a road is not modeled. Two locations snapping to the same
node produce zero road distance and two identical coordinates.

`eta_min` is an **illustrative estimate at a fixed 30 km/h**, rounded up. It is
not an actual traffic estimate. The contract has no ETA-label field, so the
label is documented here and printed by the demo; the frontend should label
it accordingly. `steps` remains empty. Road mode sets `rerouted` and
`reroute_reason` when hazards change the route relative to the no-hazard route.
Backup mode uses `rerouted: false`, `reroute_reason: null`, and a separate warning.

The finite demo graph can miss routes that leave the downloaded area. Snapping
does not verify entrance access, and routing does not model turn restrictions
or live traffic. `find_route()` avoids supplied core hazards; buffer zones do
not change routing costs. V2 forecast checks and their limits are described
above. Each request recalculates its route.
The API owner must catch `NoRouteError` and return the contract's HTTP 404 JSON.

API references used:
- https://osmnx.readthedocs.io/en/stable/user-reference.html
- https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html
