# Shepherd — API Contract (v1)

The single source of truth for how every piece talks to every other piece.
**Change nothing here without telling the team first, and log it in the Changelog.**

---

## 0. Setup everyone needs

| Thing | Value |
|---|---|
| Backend URL | `http://localhost:8000` |
| Dashboard dev server | `http://localhost:5173` |
| Phone dev server | `http://localhost:5174` |
| CORS | Backend allows all origins (`*`) during the hackathon |
| Map | MapLibre GL JS + OpenStreetMap tiles |
| Map start view | center `[-113.4938, 53.5461]` (downtown Edmonton), zoom `11` |

**Phones on the same Wi-Fi:** run the backend with `--host 0.0.0.0` and use the laptop's IP instead of `localhost`. Put the backend URL in ONE config variable in each frontend (`API_URL`) so it's a one-line change.

### Conventions
- **Coordinates in GeoJSON are `[lon, lat]`.** Edmonton is roughly lon `-113.5`, lat `53.5`. If your point lands in the ocean, you flipped them.
- Query params use names: `?lat=53.52&lon=-113.62`.
- Polygons are closed: the last coordinate equals the first.
- `sim_time` = whole minutes since the scenario started.
- IDs are strings with a prefix: `hz_` hazard, `sh_` shelter, `rp_` report.
- Errors (any non-2xx):
  ```json
  { "error": "no_route", "message": "No reachable shelter from this location" }
  ```

---

## 1. HTTP endpoints

### GET /health
```json
{ "ok": true }
```

### GET /hazards
```json
{
  "type": "FeatureCollection",
  "sim_time": 30,
  "features": [
    {
      "type": "Feature",
      "id": "hz_1",
      "properties": { "kind": "wildfire", "zone": "core", "source": "sim" },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-113.680, 53.535], [-113.670, 53.541], [-113.656, 53.541],
          [-113.646, 53.535], [-113.656, 53.529], [-113.670, 53.529],
          [-113.680, 53.535]
        ]]
      }
    }
  ]
}
```
| Field | Values |
|---|---|
| `kind` | `"wildfire"` · `"flood"` |
| `zone` | `"core"` = roads closed · `"buffer"` = roads slowed |
| `source` | `"sim"` · `"live"` · `"report"` |

### POST /hazards
Dashboard click → drop a hazard (a circle).
```json
{ "kind": "wildfire", "lat": 53.535, "lon": -113.663, "radius_m": 800 }
```
Returns `201` with the new Feature (same shape as one item in `features` above).

### DELETE /hazards
Clears all hazards (reset button). Returns `{ "ok": true }`.

### GET /shelters
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "sh_kinsmen",
      "properties": { "name": "Kinsmen Sports Centre", "capacity": 2000, "occupancy": 0, "open": true },
      "geometry": { "type": "Point", "coordinates": [-113.516, 53.519] }
    },
    {
      "type": "Feature",
      "id": "sh_terwillegar",
      "properties": { "name": "Terwillegar Rec Centre", "capacity": 2500, "occupancy": 0, "open": true },
      "geometry": { "type": "Point", "coordinates": [-113.595, 53.440] }
    },
    {
      "type": "Feature",
      "id": "sh_commonwealth",
      "properties": { "name": "Commonwealth Rec Centre", "capacity": 1500, "occupancy": 0, "open": true },
      "geometry": { "type": "Point", "coordinates": [-113.473, 53.559] }
    }
  ]
}
```
(Locations are approximate. Fine for the demo.)

### GET /route?lat=53.520&lon=-113.620
```json
{
  "shelter_id": "sh_kinsmen",
  "shelter_name": "Kinsmen Sports Centre",
  "distance_km": 8.4,
  "eta_min": 14,
  "rerouted": false,
  "reroute_reason": null,
  "steps": [
    { "instruction": "Head south on 170 St NW", "distance_km": 1.9 },
    { "instruction": "Turn left onto Whitemud Dr", "distance_km": 5.8 },
    { "instruction": "Arrive at Kinsmen Sports Centre", "distance_km": 0.7 }
  ],
  "geometry": {
    "type": "LineString",
    "coordinates": [[-113.620, 53.520], [-113.620, 53.490], [-113.540, 53.490], [-113.516, 53.519]]
  }
}
```
- `rerouted` / `reroute_reason`: `true` + a short reason when hazards changed the route since the last request. Step 0 can always send `false` / `null`.
- `steps` may be `[]` until turn-by-turn exists.
- No shelter reachable → `404` with `"error": "no_route"`.

### POST /reports
Phone buttons: Report hazard / I'm safe / Need help.
```json
{ "kind": "blocked_road", "lat": 53.530, "lon": -113.600, "note": "Tree down" }
```
| `kind` | `"fire"` · `"flooded_road"` · `"blocked_road"` · `"safe"` · `"sos"` |
|---|---|

`note` is optional. Returns `201`:
```json
{ "id": "rp_1", "received": true }
```

### GET /reports
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "rp_1",
      "properties": { "kind": "blocked_road", "note": "Tree down", "sim_time": 30 },
      "geometry": { "type": "Point", "coordinates": [-113.600, 53.530] }
    }
  ]
}
```

### GET /roads/closed   *(Step 2. Fixture only until then)*
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "rd_1",
      "properties": { "name": "Stony Plain Rd", "status": "closed", "reason": "wildfire" },
      "geometry": { "type": "LineString", "coordinates": [[-113.700, 53.541], [-113.640, 53.541]] }
    }
  ]
}
```
`status`: `"closed"` · `"slowed"`

### Simulation control   *(Step 2. Dashboard only)*
| Endpoint | Body | Returns |
|---|---|---|
| `POST /sim/start` | `{ "scenario": "wildfire", "lat": 53.535, "lon": -113.663, "wind_kmh": 35, "wind_from_deg": 315, "fuel_dryness": 0.8 }` | `/sim/state` shape |
| `POST /sim/pause` · `/sim/resume` · `/sim/reset` | none | `/sim/state` shape |
| `POST /sim/speed` | `{ "multiplier": 4 }` | `/sim/state` shape |
| `GET /sim/state` | none | `{ "state": "running", "scenario": "wildfire", "sim_time": 30, "speed": 4 }` |

`state`: `"idle"` · `"running"` · `"paused"`. Flood start body: `{ "scenario": "flood", "river_rise_m_per_hr": 0.5 }`.

---

## 2. Live updates

**Step 0–1: polling.** Frontends re-fetch `/hazards`, `/reports` (dashboard) and `/route` (phone) every **2 seconds**.

**Step 2+: WebSocket `ws://localhost:8000/ws`.** The server pushes a small "something changed" message, and clients re-fetch what's listed in `changed`.
```json
{ "type": "tick", "sim_time": 35, "changed": ["hazards", "roads"] }
```
```json
{ "type": "report", "changed": ["reports"] }
```
`type`: `"tick"` · `"report"` · `"reset"`. `changed`: any of `"hazards"`, `"roads"`, `"shelters"`, `"reports"`.

---

## 3. Python interfaces inside the backend

These are how `api/` (Harsit) calls into routing (Azer) and sim (Dviviz). Same rule: don't change a signature without telling the others.

### `backend/sim/wildfire.py` (Dviviz)
```python
class WildfireSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 20,
                 wind_from_deg: float = 315, fuel_dryness: float = 0.7): ...
    def step(self, minutes: int) -> None: ...        # advance the fire
    def features(self) -> list[dict]: ...            # GeoJSON Features, kind="wildfire"
```

### `backend/sim/flood.py` (Dviviz)
```python
class FloodSim:
    def __init__(self, river_rise_m_per_hr: float = 0.5): ...
    def step(self, minutes: int) -> None: ...
    def features(self) -> list[dict]: ...            # GeoJSON Features, kind="flood"
```
Step 0 version of both: a circle (or blob near the river) whose radius grows every `step()`.

### `backend/routing/router.py` (Azer)
```python
class NoRouteError(Exception): ...

def load_graph() -> None: ...                         # call once at startup
def find_route(lat: float, lon: float,
               hazards: list[dict],                   # GeoJSON hazard Features
               shelters: list[dict]) -> dict: ...     # returns the GET /route body
                                                      # raises NoRouteError if none reachable
def closed_roads(hazards: list[dict]) -> list[dict]: ...  # GeoJSON LineStrings (Step 2)
```
Step 0 version: `find_route` returns a straight line from the point to the nearest shelter.

---

## 4. Fixtures (fake data for frontends)

Copy each example above into its own file so the frontends can build before the backend is ready:

```
shared/fixtures/hazards.json
shared/fixtures/shelters.json
shared/fixtures/route.json
shared/fixtures/reports.json
shared/fixtures/roads_closed.json
shared/fixtures/sim_state.json
```
Frontends: one flag `USE_FIXTURES = true` → read local files; `false` → call `API_URL`.

---

## 5. Step 0 done = 
1. `GET /health` works.
2. Dashboard shows the Edmonton map + shelters + a hazard that grows every 2 s.
3. Click on the dashboard map → `POST /hazards` → the new circle appears.
4. Phone: tap to set your location → route line to a shelter drawn on the map.
5. All six PRs merged into `main`.

---

## Changelog
| When | Who | What |
|---|---|---|
| Fri 7:15 PM | Harsit | v1 agreed by team |
