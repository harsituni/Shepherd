# Shepherd — API Contract (v2.1)

The single source of truth for how every piece talks to every other piece.
**Change nothing here without telling the team first, and log it in the Changelog.**

**v2 was frozen for the final-vision build.** **v2.1** adds evacuation traffic
(BPR delays, anti-gridlock, `/traffic*`) as agreed by the team.

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

**Phones on the same Wi-Fi / judge QR:** run the backend with `--host 0.0.0.0` and put the laptop LAN IP or tunnel URL in each frontend’s `API_URL`.

### Conventions
- **Coordinates in GeoJSON are `[lon, lat]`.** Edmonton ≈ lon `-113.5`, lat `53.5`. Ocean = you flipped them.
- Query params use names: `?lat=53.52&lon=-113.62`.
- Polygons are closed: last coordinate equals first.
- `sim_time` = whole **minutes** since the scenario started (ignition / `/sim/start`).
- IDs are strings with a prefix: `hz_` hazard, `sh_` shelter, `rp_` report, `ev_` evacuee, `rt_` route option.
- Errors (any non-2xx):
  ```json
  { "error": "no_route", "message": "No reachable shelter from this location" }
  ```

### Wind & fire timing (Dviviz + Azer — read once)
- **Wind speed unit: `wind_kmh`** (kilometres per hour). Always this field name.
- **Wind direction: `wind_from_deg`** — meteorological **FROM** direction. `0` = from north, `90` = from east, `180` = from south, `270` = from west. Fire spreads roughly the opposite way (downwind).
- **`arrival_min(lat, lon)`** — simulated minute when fire first reaches that point, or `null` if not within the forecast horizon (default 120 min).
- **Road blocking rule (plain sentence):** a road segment is **blocked** if the driver would reach it **after** `arrival_min − 30` minutes (i.e. we close the road **30 minutes before** the fire is predicted to arrive).
- **Route margin** = how many minutes of spare time you have vs that rule (higher is safer).
- **Route status:**
  - `"ok"` — margin ≥ 60
  - `"tight"` — margin 0–59
  - `"blocked"` — margin &lt; 0 (or no path that stays clear)

### Scenarios
`"wildfire"` is the supported hazard. `"tornado"` is a **beta** feature: it runs end to end, but its model and outputs may change. Any other scenario gets `400` `{ "error": "unsupported_scenario" }`.

---

## 1. HTTP endpoints

### Legend
- **Step 0 (still live):** already implemented; keep working.
- **v2 (final vision):** new or expanded; implement per assigned issues.

---

### GET /health  · Step 0
```json
{ "ok": true }
```

---

### GET /hazards  · Step 0
Current burned / active hazard polygons (now), plus `sim_time`.

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
| `kind` | `"wildfire"` · `"tornado"` (beta) |
| `zone` | `"core"` = treat as impassable / urgent · `"buffer"` = slowed / caution |
| `source` | `"sim"` · `"live"` · `"report"` |

### POST /hazards  · Step 0
Dashboard click → drop a hazard circle.
```json
{ "kind": "wildfire", "lat": 53.535, "lon": -113.663, "radius_m": 800 }
```
Returns `201` with the new Feature.

### DELETE /hazards  · Step 0
Clears **dropped** hazards (not necessarily the whole sim — see `/sim/reset`). Returns `{ "ok": true }`.

---

### GET /shelters  · Step 0
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

---

### GET /route?lat=&lon=  · **v2 expanded**

The API serves the route shape in **`shared/route_v3.md`**: it extends the v2
response below with `route_status`, `no_safe_route`, an `indeterminate` status,
stable role-based option ids, road-point `access` notes and real example answers
(`shared/fixtures/route_*.json`). Read both; where they differ, `route_v3.md` wins.

**v2 response** — 2–3 options, leave-by, statuses:

```json
{
  "lat": 53.520,
  "lon": -113.620,
  "sim_time": 12,
  "leave_by_sim_min": 18,
  "leave_by_label": "Leave within 6 min (sim)",
  "best_route_id": "rt_1",
  "options": [
    {
      "id": "rt_1",
      "shelter_id": "sh_kinsmen",
      "shelter_name": "Kinsmen Sports Centre",
      "distance_km": 8.4,
      "eta_min": 14,
      "margin_min": 72,
      "status": "ok",
      "clear_until_sim_min": 90,
      "clear_until_label": "Clear until T+90",
      "reason": null,
      "geometry": {
        "type": "LineString",
        "coordinates": [[-113.620, 53.520], [-113.540, 53.500], [-113.516, 53.519]]
      }
    },
    {
      "id": "rt_2",
      "shelter_id": "sh_commonwealth",
      "shelter_name": "Commonwealth Rec Centre",
      "distance_km": 6.1,
      "eta_min": 11,
      "margin_min": 25,
      "status": "tight",
      "clear_until_sim_min": 48,
      "clear_until_label": "Clear until T+48",
      "reason": null,
      "geometry": {
        "type": "LineString",
        "coordinates": [[-113.620, 53.520], [-113.473, 53.559]]
      }
    },
    {
      "id": "rt_3",
      "shelter_id": "sh_terwillegar",
      "shelter_name": "Terwillegar Rec Centre",
      "distance_km": 12.0,
      "eta_min": 22,
      "margin_min": -8,
      "status": "blocked",
      "clear_until_sim_min": null,
      "clear_until_label": null,
      "reason": "Blocked near Whitemud: fire arrives at T+40; you would reach that segment at T+55 (needs T+10 with 30 min buffer).",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-113.620, 53.520], [-113.595, 53.440]]
      }
    }
  ],
  "excluded": [
    {
      "shelter_id": "sh_terwillegar",
      "reason": "Same as rt_3 — listed for UI grey cards if not duplicated in options."
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `leave_by_sim_min` | Latest **sim minute** you should start the **best usable** (`ok`/`tight`) route; `null` if none |
| `margin_min` | Spare minutes vs fire buffer rule |
| `status` | `"ok"` · `"tight"` · `"blocked"` |
| `clear_until_sim_min` | Sim minute until which this route stays clear under current forecast |
| `reason` | Required when `status` is `"blocked"`; otherwise `null` |
| `excluded` | Optional extra blocked attempts with reasons (may be `[]`) |
| `traffic_delay_min` | **v2.1** Extra minutes vs free-flow on this option (`0` when traffic is off) |
| `traffic_free_min` | **v2.1** Free-flow travel minutes for the same geometry |

When **traffic is enabled** (`POST /traffic/config`), `eta_min` / `modeled_duration_min` use congested (BPR) travel times, so jams can push a route from `ok`/`tight` to `blocked` against the fire buffer rule.

**Compatibility (Step 0):** until frontends migrate, the API **may also** include the old flat fields copying `options[0]` when present (`shelter_id`, `geometry`, `eta_min`, …) plus `rerouted` / `steps`. New phone/dashboard **must** read `options` + `leave_by_*`.

- `404` `{ "error": "no_route", "message": "..." }` only outside the demo area, with no road within 300 m, or with no open shelter reachable by road. "Everything is blocked" is a `200` with `no_safe_route: true`.

**Optional v2 query:** `GET /route?lat=&lon=&check_route_id=rt_1` — re-check a chosen route after wind change (same response shape; `best_route_id` may change).

**Optional v2.1 query:** `GET /route/traffic_hint?lat=&lon=&route_id=rt_1` — phone banner helper when a faster traffic-aware route exists (see Traffic below).

---

### POST /reports  · Step 0
```json
{ "kind": "blocked_road", "lat": 53.530, "lon": -113.600, "note": "Tree down" }
```
| `kind` | `"fire"` · `"blocked_road"` · `"other"` · `"safe"` · `"sos"` |

Returns `201`: `{ "id": "rp_1", "received": true }`.

### GET /reports  · Step 0
FeatureCollection of Point features (see v1 examples). Phone reports for the dashboard.

---

### GET /forecast  · **v2 new**
Predicted fire outlines for the map (not the same as “now” in `/hazards`, though they should be consistent).

```json
{
  "sim_time": 12,
  "horizon_min": 120,
  "wind_kmh": 35,
  "wind_from_deg": 270,
  "outlines": [
    {
      "t_min": 15,
      "type": "Feature",
      "id": "fc_15",
      "properties": { "kind": "wildfire", "t_min": 15, "zone": "predicted" },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-113.700, 53.540], [-113.650, 53.545], [-113.640, 53.530],
          [-113.690, 53.525], [-113.700, 53.540]
        ]]
      }
    },
    {
      "t_min": 30,
      "type": "Feature",
      "id": "fc_30",
      "properties": { "kind": "wildfire", "t_min": 30, "zone": "predicted" },
      "geometry": { "type": "Polygon", "coordinates": [[[-113.71, 53.54], [-113.64, 53.55], [-113.63, 53.52], [-113.70, 53.52], [-113.71, 53.54]]] }
    }
  ]
}
```

`outlines` **must** include entries for **t_min = 15, 30, 45, 60, 75, 90, 105, 120** when a wildfire sim is running. If sim is `idle`, return `"outlines": []` and `200`.

---

### POST /sim/wind  · **v2 new**
Dashboard wind control. Reruns Dviviz forecast.

```json
{ "wind_kmh": 40, "wind_from_deg": 270 }
```

Returns `/sim/state` shape (below), after forecast rebuild has been kicked off (may still be computing; clients should re-fetch `/forecast` and `/route` over the next few seconds).

---

### Simulation control  · **v2 required for dashboard** (was “Step 2” in v1)

| Endpoint | Body | Returns |
|---|---|---|
| `GET /sim/state` | none | state object below |
| `POST /sim/start` | wildfire start body | state object |
| `POST /sim/pause` | none | state object |
| `POST /sim/resume` | none | state object |
| `POST /sim/reset` | none | state object |
| `POST /sim/speed` | `{ "multiplier": 4 }` | state object |

#### GET /sim/state
```json
{
  "state": "running",
  "scenario": "wildfire",
  "sim_time": 30,
  "speed": 4,
  "wind_kmh": 35,
  "wind_from_deg": 315,
  "traffic": {
    "enabled": false,
    "anti_gridlock": true,
    "simulated_count": 10000,
    "real_count": 0,
    "active_count": 0,
    "metrics": {
      "clearance_min": null,
      "avg_eta_min": null,
      "max_vc": 0,
      "jammed_edges": 0,
      "agents_active": 0,
      "agents_arrived": 0,
      "reroutes": 0
    },
    "compare": null,
    "last_rebalance_sim_min": null
  }
}
```
`state`: `"idle"` · `"running"` · `"paused"`.  
`speed`: `1` · `4` · `16`.  
`scenario`: `"wildfire"` · `"tornado"` or `null` when idle.  
`traffic`: **v2.1** summary (same shape as `GET /traffic/state` without `sim_time`). Always present; volumes are empty while `enabled` is false.

#### POST /sim/start
```json
{
  "scenario": "wildfire",
  "lat": 53.535,
  "lon": -113.663,
  "wind_kmh": 35,
  "wind_from_deg": 315,
  "fuel_dryness": 0.8,
  "humidity_pct": 22
}
```
`humidity_pct` optional. An unknown scenario → `400` `{ "error": "unsupported_scenario", "message": "..." }`.  
`"scenario": "tornado"` (**beta**) accepted (dashboard path direction uses `wind_kmh` / `wind_from_deg`; optional `ef_rating` 0–5). Starting a sim recentres the traffic crowd on `(lat, lon)`.

---

### Traffic  · **v2.1 new**

Evacuation traffic for demos: each road has a capacity from its OSM class and lanes;
travel time follows the Bureau of Public Roads (BPR) formula
\(t = t_0\,(1 + 0.15\,(v/c)^4)\). A crowd of **simulated cars** plus **real phone**
pins (`POST /evacuees`) loads the network. With **anti-gridlock** on, cars are
routed one at a time, rebalanced every **5 sim-minutes**, and switched only when the
new route saves **≥ 3 minutes** (with a cooldown so routes do not flip-flop).

| Endpoint | Body | Returns |
|---|---|---|
| `GET /traffic` | none | state + `edges` FeatureCollection (map colouring) |
| `GET /traffic/state` | none | compact state (no geometries) |
| `GET /traffic/projection?lat=&lon=&scenario=&wind_kmh=&when=` | none | people/cars estimate for the pin |
| `POST /traffic/config` | config body below | state |
| `POST /traffic/compare` | none | compare payload + state |
| `POST /traffic/rebalance` | none | state (force reassignment) |
| `GET /route/traffic_hint?lat=&lon=&route_id=` | none | `{ "hint": …, "sim_time": … }` |

#### POST /traffic/config
```json
{ "enabled": true, "anti_gridlock": true, "simulated_count": 10000 }
```
All fields optional; omitted keys stay unchanged. `simulated_count` is clamped to `0…100000`. Large counts are a **projection**: the engine keeps a few thousand route agents and scales each one's road load so the map/metrics read as N cars without freezing the API.

#### GET /traffic/projection
Estimates evacuating **people** and **cars** from the hazard pin using Edmonton zone densities × footprint × local day/time occupancy (`America/Edmonton`). `when` is optional ISO-8601 (defaults to now). `POST /sim/start` uses this to set `simulated_count` automatically.
```json
{
  "ok": true,
  "people": 28400,
  "cars": 12070,
  "area_label": "Jasper Place / west end",
  "daypart": "weekday midday",
  "radius_km": 2.7,
  "density_per_km2": 2800,
  "label": "~28,400 people / 12,070 cars · Jasper Place / west end · weekday midday",
  "method": "edmonton_zone_density_v1"
}
```

#### GET /traffic (and `/traffic/state`)
```json
{
  "enabled": true,
  "anti_gridlock": true,
  "simulated_count": 10000,
  "real_count": 3,
  "active_count": 10003,
  "sim_time": 30,
  "metrics": {
    "clearance_min": 41.0,
    "avg_eta_min": 18.2,
    "max_vc": 1.6,
    "jammed_edges": 24,
    "agents_active": 10003,
    "agents_arrived": 0,
    "reroutes": 12
  },
  "compare": {
    "without_min": 74.0,
    "with_min": 41.0,
    "saved_min": 33.0,
    "label": "Clearance time 74 → 41 min"
  },
  "last_rebalance_sim_min": 30,
  "edges": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "id": "tr_42",
        "properties": {
          "edge": 42,
          "name": "Whyte Avenue",
          "highway": "primary",
          "lanes": 2,
          "volume": 28.0,
          "capacity": 22.0,
          "vc_ratio": 1.27,
          "level": "jammed",
          "free_min": 0.4,
          "travel_min": 0.9
        },
        "geometry": {
          "type": "LineString",
          "coordinates": [[-113.500, 53.518], [-113.495, 53.518]]
        }
      }
    ]
  }
}
```
`GET /traffic/state` is the same object **without** `edges`.  
`level`: `"free"` · `"busy"` · `"jammed"` · `"gridlock"` from `vc_ratio`.  
`compare` is `null` until `POST /traffic/compare` has been called this session.

#### POST /traffic/compare
Runs a naive pile-up assignment, then anti-gridlock, and returns:
```json
{
  "ok": true,
  "without_min": 74.0,
  "with_min": 41.0,
  "saved_min": 33.0,
  "label": "Clearance time 74 → 41 min",
  "enabled": true,
  "anti_gridlock": true,
  "metrics": { "clearance_min": 41.0 }
}
```
Leaves anti-gridlock **on** afterward (the “after” state) when traffic remains enabled.

#### GET /route/traffic_hint
```json
{
  "sim_time": 30,
  "hint": {
    "route_id": "rt_sh_terwillegar_fastest",
    "shelter_id": "sh_terwillegar",
    "saves_min": 5,
    "message": "Faster route available, saves 5 min",
    "reason": "traffic"
  }
}
```
`hint` is `null` when traffic is off, no better route exists, or the saving is under 1 minute.

**Dashboard (v2.1):** colour roads from `GET /traffic` → `edges`, evacuee-count slider + anti-gridlock switch via `POST /traffic/config`, metrics from `traffic.metrics` / `/sim/state`, Compare button → `POST /traffic/compare`.  
**Phone (v2.1):** show `+N min traffic` from `traffic_delay_min` on route cards; poll `/route/traffic_hint` for the faster-route banner; when the phone swaps routes for traffic, surface `reason: "traffic"`.

---

### POST /evacuees  · **v2 new**
Phone heartbeat every ~2 s while evacuating.

```json
{
  "id": "ev_judge_3",
  "lat": 53.521,
  "lon": -113.610,
  "route_id": "rt_1",
  "route_status": "ok",
  "shelter_id": "sh_kinsmen",
  "route_coords": [[-113.610, 53.521], [-113.516, 53.519]]
}
```
Upserts by `id`. `route_coords` is optional (`[[lon, lat], …]` of the path the phone is driving) so the dashboard can draw live routes. Returns `200` or `201`:
```json
{ "id": "ev_judge_3", "received": true }
```

### GET /evacuees  · **v2 new**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "ev_judge_3",
      "properties": {
        "route_id": "rt_1",
        "route_status": "ok",
        "shelter_id": "sh_kinsmen",
        "updated_sim_time": 14,
        "reroutes": 1,
        "route_coords": [[-113.610, 53.521], [-113.516, 53.519]]
      },
      "geometry": { "type": "Point", "coordinates": [-113.610, 53.521] }
    }
  ]
}
```
`reroutes` counts mid-trip `route_id` changes for that phone. Dashboard polls every 2 s. Servers **may** drop evacuees with no POST for 30+ seconds — if so, document in changelog when implemented.

---

### GET /roads/closed  · **v2.1**
OSM edges already past the fire close deadline (`arrival_min − 30`). Dashboard paints these as closed corridors while the fire (or tornado) runs.

```json
{
  "type": "FeatureCollection",
  "sim_time": 30,
  "count": 84,
  "features": [
    {
      "type": "Feature",
      "id": "rd_closed_42",
      "properties": {
        "kind": "closed_road",
        "name": "Whyte Avenue",
        "edge": 42,
        "closed_at_sim_min": 18,
        "reason": "fire"
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[-113.500, 53.518], [-113.495, 53.518]]
      }
    }
  ]
}
```
`count` is the full closed set; `features` may be capped for the map payload. Empty while idle / no oracle.

---

## 2. Live updates

**Hackathon default: polling every 2 seconds.**
- Phone: `/route` (or check), `/hazards`, `POST /evacuees`; with traffic on, also `/route/traffic_hint`
- Dashboard: `/hazards`, `/reports`, `/forecast`, `/evacuees`, `/sim/state`, `/roads/closed`; with traffic on, also `/traffic` or `/traffic/state`

**Later:** WebSocket `ws://localhost:8000/ws` with `{ "type", "sim_time", "changed": [...] }` — unchanged idea from v1; not required for Saturday.

---

## 3. Python interfaces inside the backend

Do not change a signature without telling the team and updating this file.

### `backend/sim/wildfire.py` (Dviviz)
`TornadoSim` (`backend/sim/tornado.py`, **beta**) has the same surface.
```python
class WildfireSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 20,
                 wind_from_deg: float = 315, fuel_dryness: float = 0.7, ...): ...
    def step(self, minutes: int) -> None: ...
    def features(self) -> list[dict]: ...   # GeoJSON Features, kind="wildfire" (NOW)
    def forecast(self, horizon_min: int = 120) -> list[dict]: ...  # outlines at 15-min steps
    def set_wind(self, wind_kmh: float, wind_from_deg: float) -> None: ...
    def oracle(self) -> ForecastOracle: ...  # frozen arrival-grid snapshot for routing
```

### `backend/routing/router.py` (Azer)
```python
class NoRouteError(Exception): ...

def load_graph() -> None: ...

def find_routes(lat: float, lon: float, oracle, shelters: list[dict], sim_time: int = 0,
                check_route_id=None, debug: bool = False,
                hazards=None, forecast_outlines=None) -> dict:
    """Returns the GET /route body (shared/route_v3.md); oracle is None with no fire."""
```

**Blocking rule again:** segment blocked if driver would arrive after `arrival_min − 30`.

---

## 4. Fixtures

```
shared/fixtures/hazards.json, shelters.json, reports.json, notifications.json
shared/fixtures/forecast.json      # GET /forecast example
shared/fixtures/evacuees.json      # GET /evacuees example
shared/fixtures/route_*.json       # real GET /route answers (python -m backend.routing.tools.route_fixtures)
```

`USE_FIXTURES = true` → local JSON; `false` → `API_URL`.

---

## 5. What “done” means now

### Step 0 (already shipped)
1. `/health`, map, shelters, growing fire, click hazard, phone route, reports.

### Final vision (Saturday night target)
1. Fire **forecast** outlines (+15…+120) and `arrival_min`.
2. **Time-aware** routes with 2–3 options, margins, leave-by.
3. Dashboard **wind** changes forecast; a chosen route can go red.
4. Phone shows leave-by + cards and offers a new route when blocked.
5. Dashboard shows **evacuee dots** from all phones.
6. Judges join via **QR / public URL**.
7. **v2.1 Traffic:** BPR road delays, anti-gridlock assignment, dashboard compare / phone delay cues.

---

## Changelog

| When | Who | What |
|---|---|---|
| Fri (hackathon start) | Harsit | v1 agreed by team |
| Sat (final vision) | Harsit | **v2:** multi-option `/route`, `/forecast`, `/sim/wind`, `/evacuees`, wind units (`wind_kmh` + `wind_from_deg` FROM), road block = arrive after `arrival_min − 30`, flood deferred, sim control required for dashboard, Python `find_routes` / `arrival_min` / `set_wind` |
| Sun | Harsit | **v2.1:** evacuation traffic — BPR capacities, simulated crowd + phones, anti-gridlock rebalance, `/traffic*` + `/route/traffic_hint`, route `traffic_delay_min` / `traffic_free_min`, `/sim/state.traffic` |
| Cleanup | Dv | Flood removed (scenario and `flooded_road` report kind); tornado marked **beta**; old v2 router removed, `/route` points at `route_v3.md`; `other` report kind listed; Python interfaces and fixtures list match the code |
| Leave-by | Dv | `/route` (`route_v3.md`): leave-by = earlier of 30 min before the evacuation zone reaches the pin and the route's road deadline; new `at_risk`, `zone_reach_sim_min`, `recommendation_note`, per-option `closer_to_fire`; no leave-by when not at risk within 4 h. The phone counts leave-by down on its own clock |
