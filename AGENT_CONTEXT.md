# Shepherd — Agent Context (Step 0: bare bones)

You are helping a 5-person team at natHacks 2026 (64-hour hackathon, Defense & Security theme).
Read this whole file before writing code. API shapes are defined in `shared/contract.md`; follow them exactly.

## What we're building
An evacuation system for Edmonton, AB:
- **Dashboard** (emergency managers): map showing hazards (wildfire/flood), shelters, phone reports.
- **Phone web app** (public): your route to the nearest shelter, redrawn when hazards change.
- **FastAPI backend**: holds state, runs a fake hazard sim, returns routes.

**Step 0 goal = fake everything, connect everything.** No real algorithms yet. Simplest code that returns the right shapes.

## Hard rules
1. **Only edit files in the folder you were told you're working on.** Never touch other folders.
2. **Never edit `shared/contract.md`.** If something in it seems wrong, say so instead of working around it.
3. **GeoJSON coordinates are `[lon, lat]`.** Edmonton ≈ lon `-113.5`, lat `53.5`. Query params are named (`?lat=..&lon=..`).
4. **No new dependencies** beyond those listed below without asking.
5. No database, no auth, no Docker. State lives in memory.
6. Keep it small and readable. Code is reviewed by humans.

## Repo layout
```
shepherd/
├── backend/
│   ├── __init__.py
│   ├── requirements.txt        # fastapi uvicorn (Harsit owns)
│   ├── api/       → Harsit
│   ├── routing/   → Azer
│   └── sim/       → Dviviz
├── dashboard/     → Shriyaz
├── phone/         → Aarya
└── shared/
    ├── contract.md
    └── fixtures/  → Harsit
```
Run everything from the repo root. Python imports are absolute: `from backend.sim.wildfire import WildfireSim`.

---

## Folder: `backend/sim/` (Dviviz)
**Delivers:** `wildfire.py` and `flood.py`, pure Python (stdlib `math` only, no FastAPI imports).
```python
class WildfireSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 20,
                 wind_from_deg: float = 315, fuel_dryness: float = 0.7): ...
    def step(self, minutes: int) -> None: ...
    def features(self) -> list[dict]: ...

class FloodSim:
    def __init__(self, river_rise_m_per_hr: float = 0.5): ...
    def step(self, minutes: int) -> None: ...
    def features(self) -> list[dict]: ...
```
**Step 0 behaviour:**
- `WildfireSim`: a circle centred on (lat, lon). Radius starts at 300 m and grows 40 m per simulated minute, capped at 5 km.
- `FloodSim`: same idea, a circle near the river at lat `53.532`, lon `-113.497`, starting at 200 m and growing 20 m per minute.
- `features()` returns a list with ONE GeoJSON Feature: a `Polygon` with 32 points, closed (last point == first), `[lon, lat]` order, `id` like `"hz_sim_fire"`, `properties = {"kind": "wildfire"|"flood", "zone": "core", "source": "sim"}`.
- Metres → degrees: `dlat = m / 111320`, `dlon = m / (111320 * cos(radians(lat)))`.

**Receives:** constructor args and `step(minutes)` calls from `backend/api`.

---

## Folder: `backend/routing/` (Azer)
**Delivers:** `router.py`, pure Python (stdlib only for Step 0, no FastAPI imports).
```python
class NoRouteError(Exception): ...

def load_graph() -> None: ...           # Step 0: does nothing
def find_route(lat: float, lon: float,
               hazards: list[dict],      # GeoJSON hazard Features
               shelters: list[dict]) -> dict: ...
```
**Step 0 behaviour:**
- Ignore `hazards`.
- Pick the nearest shelter with `properties.open == true` by haversine distance. None open → raise `NoRouteError`.
- Return a dict matching the **`GET /route` response in contract.md**: `geometry` is a `LineString` with two points (start → shelter, `[lon, lat]`), `distance_km` = haversine (rounded to 0.1), `eta_min` = `round(distance_km / 40 * 60)` (40 km/h), `rerouted: false`, `reroute_reason: null`, `steps: []`.

**Receives:** calls from `backend/api` with the current hazards and shelters.

---

## Folder: `backend/api/` (Harsit)
**Delivers:** `main.py` with a FastAPI `app`. Run with:
`uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000`
- CORS: allow all origins, methods and headers.
- Endpoints exactly as in contract.md: `GET /health`, `GET /hazards`, `POST /hazards`, `DELETE /hazards`, `GET /shelters`, `GET /route`, `POST /reports`, `GET /reports`.
- State in memory: the list of dropped hazards, the list of reports, 3 hard-coded shelters (from contract.md), one `WildfireSim` started at lat `53.535`, lon `-113.663`, and an `int sim_time`.
- Background task: every **2 s** real time, call `sim.step(1)` and `sim_time += 1`.
- `GET /hazards` = sim `features()` + dropped hazards, wrapped in a FeatureCollection with `sim_time`.
- `POST /hazards` = build a 32-point circle polygon from lat, lon and radius_m, with `source: "sim"`.
- `GET /route` = `router.find_route(lat, lon, all_hazards, shelters)`. On `NoRouteError` → 404 `{"error":"no_route","message":"..."}`.
- Report ids are `rp_1`, `rp_2`, …; hazard ids are `hz_1`, `hz_2`, …

**Receives:** `WildfireSim` from `backend/sim`, `find_route` from `backend/routing`, HTTP requests from both frontends.

## Folder: `shared/fixtures/` (Harsit)
**Delivers:** `hazards.json`, `shelters.json`, `route.json`, `reports.json`, copied exactly from the examples in contract.md. Frontends read these when `USE_FIXTURES = true`.

---

## Folder: `dashboard/` (Shriyaz)
**Stack:** Vite + React + `maplibre-gl`. Dev server on port **5173**. Own `package.json` in this folder.
**Delivers:**
- `src/config.js`: `export const API_URL = "http://localhost:8000"; export const USE_FIXTURES = false;`
- A full-window MapLibre map centred on `[-113.4938, 53.5461]`, zoom 11, OSM raster basemap:
  `{ version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } }, layers: [{ id: "osm", type: "raster", source: "osm" }] }`
- Layers:
  - hazards: fill, orange for wildfire, blue for flood, ~40% opacity, plus an outline
  - shelters: green circles with a name label
  - reports: red circles
- Polls `GET /hazards` and `GET /reports` every **2 s**. Loads `GET /shelters` once.
- **Click the map** → `POST /hazards` with `{kind:"wildfire", lat, lon, radius_m: 800}`.
- A small "Clear hazards" button → `DELETE /hazards`.
- When `USE_FIXTURES` is true, read from `shared/fixtures/*.json` instead of the API.

**Receives:** JSON from the backend (shapes in contract.md).

---

## Folder: `phone/` (Aarya)
**Stack:** Vite + React + `maplibre-gl`. Dev server on port **5174**. Own `package.json` in this folder.
**Delivers:**
- `src/config.js`: same two exports as the dashboard.
- Phone-sized layout (designed for ~390 px wide): map on top, info card below.
- Same OSM basemap and start view as the dashboard.
- **Tap the map** = set "my location" (blue dot).
- Once a location is set: poll `GET /route?lat=&lon=` every **2 s**. Draw `geometry` as a thick cyan line, and show `shelter_name`, `eta_min` and `distance_km` in the card. On a 404, show "No safe route found".
- Also poll `GET /hazards` every 2 s and draw them (same style as the dashboard). Load `GET /shelters` once.
- **"Report hazard" button** → `POST /reports` with `{kind:"blocked_road", lat, lon}` at my location, then show a "Report sent" toast.
- When `USE_FIXTURES` is true, read from `shared/fixtures/*.json`.

**Receives:** JSON from the backend (shapes in contract.md).

---

## Step 0 is done when
1. `uvicorn backend.api.main:app --port 8000` runs, and `GET /health` returns `{"ok": true}`.
2. The dashboard shows the Edmonton map, 3 shelters, and a fire circle that grows every 2 s.
3. Clicking the dashboard map adds a new hazard circle.
4. On the phone, tapping the map draws a route line to the nearest shelter with ETA and distance.
5. A phone report shows up as a red dot on the dashboard within 2 s.

## Not in Step 0 (don't build yet)
Real road routing, avoiding hazards, WebSocket, sim controls (start/pause/speed), closed roads, live data feeds, shelter capacity logic, turn-by-turn.

## How to prompt with this file
Start each prompt with: *"I'm working ONLY in `<folder>`. Follow @AGENT_CONTEXT.md and @shared/contract.md."*
