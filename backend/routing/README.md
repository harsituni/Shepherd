# Step 1 routing

This prototype chooses the shortest reachable road route to an open shelter
with spare capacity. Hazards are accepted but ignored. It does not establish
that a route is safe, hazard-free, or currently drivable.

## Setup

Run these PowerShell commands from the repository root:

```powershell
python -m venv backend/routing/.venv
backend/routing/.venv/Scripts/python.exe -m pip install "osmnx>=2,<3" "networkx>=3,<4" "scikit-learn>=1.5,<2"
```

Harsit should add these dependencies to the shared requirements file:

```text
osmnx>=2,<3
networkx>=3,<4
scikit-learn>=1.5,<2
```

OSMnx installs Shapely as a dependency. Scikit-learn supports nearest-node
lookups on the unprojected longitude/latitude graph. No shared files were edited.

## Offline tests

```powershell
backend/routing/.venv/Scripts/python.exe -B -m unittest discover -s backend/routing -v
```

The tests use a tiny NetworkX graph, real OSMnx nearest-node lookups, and real
GraphML save/load. Only the road download is mocked. No internet is needed
once the packages are installed.

## Real Edmonton demo (run separately)

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

Relative paths are resolved from the current working directory. An explicit
path must point to an existing file; missing files raise a clear error without
contacting Overpass. Load errors also propagate without a download fallback.
Set the variable before the first `load_graph()` call; later calls reuse memory.

When the variable is unset, the first run downloads driving roads from OpenStreetMap through Overpass.
The demo area is longitude -113.70 to -113.43 and latitude 53.42 to 53.58.
The graph is saved at `backend/routing/data/edmonton_drive.graphml`.
Later processes load that file; repeat calls in the same process reuse memory.
The cache and virtual environment are ignored by the routing .gitignore.

Download or file errors are shown to the caller; there is no straight-line
fallback. If the download fails, check the reported network/server error and
retry later. A successful offline test run does not prove a live download works.

## What each function does

- `NoRouteError`: signals that no eligible shelter is reachable in the demo graph.
- `load_graph()`: reads saved roads, or downloads and saves them the first time.
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
  the shortest result using the unchanged contract fields.
- `closed_roads()`: still returns an empty list as a Step 2 placeholder.
- `demo.main()`: loads the roads and prints a route using three sample shelters.

## Response details and limits

Coordinates use `[longitude, latitude]`. Distance is the sum of selected road
edge lengths, converted from metres to kilometres. Routes begin and end at
snapped road nodes, not exact user coordinates or building entrances. Access
from a building to a road is not modeled. Two locations snapping to the same
node produce zero road distance and two identical coordinates.

`eta_min` is an **illustrative estimate at a fixed 30 km/h**, rounded up. It is
not an actual traffic estimate. The contract has no ETA-label field, so the
label is documented here and printed by the demo; the frontend should label
it accordingly. `steps` remains empty, `rerouted` is false, and
`reroute_reason` is null.

The finite demo graph can miss routes that leave the downloaded area. Snapping
does not verify entrance access, and routing does not model turn restrictions,
live closures, disasters, or traffic. There is no automatic rerouting.
The API owner must catch `NoRouteError` and return the contract's HTTP 404 JSON.

API references used:
- https://osmnx.readthedocs.io/en/stable/user-reference.html
- https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html
