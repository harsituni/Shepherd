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

```powershell
backend/routing/.venv/Scripts/python.exe -B backend/routing/demo.py
```

The demo uses the contract's approximate shelter locations and fictional
availability. Its user is at latitude 53.520, longitude -113.620.
It prints the selected shelter, road distance, illustrative ETA, and GeoJSON.

The first run downloads driving roads from OpenStreetMap through Overpass.
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
