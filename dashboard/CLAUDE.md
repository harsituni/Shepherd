# Shepherd dashboard: CLAUDE.md

Owner: TechShriyaz (also owns `phone/`). Only edit files in `dashboard/` unless told otherwise.

## What this is
The Shepherd command dashboard for the Government of Alberta. Officials use it to simulate and monitor natural disasters around Edmonton/Alberta, see who's at risk, reroute evacuees and push updates to residents. Part of the natHacks 2026 project (Defense & Security theme). The public side is the phone web app in `phone/`.

## Features (in priority order)
1. **Disaster simulation + conditions.** Hazards: wildfire (main priority) and tornado. Flood was removed from the simulation.
   - Pick hazard type, click the map to place the start point.
   - Conditions: wind speed and wind direction (both hazards; for a tornado the direction is its path), relative humidity (wildfire only). No fuel dryness control (the backend default is used) and no temperature control. Direction options read start → finish, e.g. "West → East".
   - Play / pause / reset, speed 1× / 4× / 16×, elapsed time (T+min).
   - Live / Simulation mode switch: Live = real data feeds, Simulation = run a scenario. (Internally the mode value is still `drill`.)
2. **Rerouting map with predicted path.**
   - Current hazard (solid orange, shading to dark red `#7A1F0A` at the centre for wildfire) plus predicted spread as red dotted rings (no fill) labelled T+30 / T+60 min; toggle "Show predicted path".
   - Closed roads in red, evacuation routes in blue, shelters as navy squares, all redrawn when the hazard changes.
   - **Rerouting updates feed** in the right panel: timestamped events, e.g. "T+24 · Stony Plain Rd closed · 142 evacuees rerouted to Kinsmen Sports Centre".
3. **Historical progression slider.** A timeline slider under the map that scrubs from T+0 to now, redrawing the hazard, closed roads and routes as they were at that step, and on past now into the forecast (up to the `/forecast` horizon, +120 min), drawing the fire as predicted for that minute. Dragging it pauses the sim; a "Back to live" button returns to the current step.
4. **High-priority residents.** Map layer + list of residents who need extra help evacuating (e.g. disabled, no vehicle). Show only what responders need: location pin, needs category, evacuation status (not started / en route / safe / needs pickup). Toggleable layer. Demo uses fake, generated residents only; never real personal data.
5. **Notify all residents.** A "Send update" panel: title, message, severity (Advisory / Alert / Evacuation order), target area (whole region or inside the hazard zone). Sends to the backend, which pushes it to every phone as a top-of-screen notification. Show a sent-history list.
6. **Reported hazards.** A list/tab of everything phones have reported (fire, flooded road, blocked road, SOS, I'm safe), newest first, with type, time, location and status (New / Verified / Dismissed). Each report also appears as a pin on the map; clicking a list item centres the map on it.

## Key numbers (only these 4 tiles)
People at risk · Roads closed · Active reroutes · Shelter capacity used.

## Layout (matches the approved mockup)
- Mockup: `design/dashboard-mockup.html` (screenshot `design/dashboardpic.png`). Visual reference only; rebuild as React components with MapLibre in place of the sketched SVG map.
- Header (Alberta blue `#005072`): placeholder logo, Shepherd name, "Disaster monitoring · Alberta", Live/Simulation switch, last-updated time.
- Thin light-blue incident banner under it (current hazard + status).
- Left panel: Simulate & predict controls.
- Centre: full map, legend bottom-left, zoom top-right, history slider along the bottom.
- Right panel: 4 stat tiles, then tabs: **Reports** (hazard reports; reports from high-priority residents are specially marked) · **Notify** (send update + history; severity colours: Alert deep yellow `#9A6B00`, Evacuation order deep red `#8A2F06`). No separate Updates or Priority tabs.
- Fluid page layout; panels stack on narrow screens.

## Design
- **Visual system: see `/DESIGN.md`** (shared with `phone/`; tokens, components, rules). If it and this section disagree, flag it rather than picking one.
- Minimalist, inspired by Alberta.ca's wildfire pages: plain blue and white, lots of whitespace, no decorative charts.
- Colours: header `#005072` (Alberta's brand dark blue, same as phone), navy `#0B3D6E` (shelters, selected states, outline buttons), blue `#0070C4` (primary, routes), tint `#EAF3FB` (incident banner only), borders `#D3E3F2`, text `#0B2545`, muted text `#3B5A7A`.
- Gold `#FEBA35` only for the 3px keyboard focus ring (as on Alberta.ca).
- Orange `#D9480F` only for the active hazard (dark red `#7A1F0A` for a wildfire's centre), red `#C62828` only for closed roads (solid), the predicted path (dotted) and SOS reports.
- Font: **Public Sans** (Google Fonts, weights 400/500/600/700), fallback `system-ui, sans-serif`. Use `font-variant-numeric: tabular-nums` for stats and times. Type scale 14/16/18/20px (plus 26px stat values; nothing under 14); section titles are plain sentence-case headings, not uppercase labels.
- Corners: 6px on controls, 8px on cards. No pills (the Live/Simulation switch is a segmented control). Flat surfaces separated by 1px borders, not shadows (one soft shadow only on floating pop-ups).
- One solid button per area; others are navy outlines. Disabled controls get a flat style, never `opacity`; a locked selection stays visible.
- Touch targets ≥44px, text contrast ≥4.5:1.
- Don't use the Government of Alberta logo or wordmark; this is Shepherd's own branding.

## Don't (looks AI-generated)
- No Inter, Roboto, Poppins, Montserrat, DM Sans, Manrope, Space Grotesk, Plus Jakarta Sans, Geist, Outfit or any other default "AI website" font. Public Sans only.
- No gradients of any kind: no gradient backgrounds, buttons, text or glows. Solid colours only.
- No emoji as icons; use simple inline stroke SVG icons.
- No glassmorphism/blur, neon glows, coloured left-border accent cards, oversized rounded "bubble" cards or bouncy animations.
- No filler stats, decorative charts or lorem ipsum; every number on screen comes from the backend or a fixture.
- Keep it looking like a clean government service page: white background, navy/blue accents, plain hierarchy.

## Stack
- Vite + React + `maplibre-gl`, OpenStreetMap basemap, our data drawn as GeoJSON layers.
- Own `package.json` inside `dashboard/`.
- `src/config.js` exports `API_URL` (default `http://localhost:8000`) and `USE_FIXTURES` (true until the backend is ready).
- Map starts centred on Edmonton.

## API this app uses (from `shared/contract.md` v1)
- Backend `http://localhost:8000` · this app runs on port **5173** · map starts at `[-113.4938, 53.5461]`, zoom `11`.
- `GET /hazards`: FeatureCollection with `sim_time`; each feature has `kind` (`wildfire`|`flood`), `zone` (`core` = draw solid, roads closed · `buffer` = draw lighter, roads slowed), `source` (`sim`|`live`|`report`).
- `POST /hazards` `{ kind, lat, lon, radius_m }` on map click (201 → the new Feature). `DELETE /hazards` for Reset.
- `GET /shelters`: Points with `name`, `capacity`, `occupancy`, `open` (shelter capacity tile = sum occupancy / sum capacity).
- `GET /reports`: Points with `kind` (`fire`|`flooded_road`|`blocked_road`|`safe`|`sos`), `note`, `sim_time`. Feeds the Reports tab and map pins.
- `GET /roads/closed` (Step 2, fixture until then): LineStrings with `name`, `status` (`closed` = solid red, `slowed` = dashed red), `reason`. Feeds "Roads closed" and the Updates feed.
- Sim control (Step 2): `POST /sim/start` `{ scenario, lat, lon, wind_kmh, wind_from_deg, fuel_dryness }` (`fuel_dryness` 0–1, `wind_from_deg` compass degrees); flood: `{ scenario: "flood", river_rise_m_per_hr }`. `POST /sim/pause|resume|reset`, `POST /sim/speed { multiplier }`, `GET /sim/state` → `{ state: idle|running|paused, scenario, sim_time, speed }`. `POST /sim/wind { wind_kmh, wind_from_deg }` (contract v2, both required) changes wind mid-run; wind speed is the one condition that stays unlocked after start.
- `GET /forecast` (contract v2): `{ sim_time, horizon_min, wind_kmh, wind_from_deg, outlines }`, each outline a Polygon Feature with `t_min` (15, 30 … 120 minutes from now); `outlines: []` when idle. Polled with `/hazards`; the dashboard draws the 30 and 60 min outlines as the predicted path (`FORECAST_MIN_SHOWN` in `src/history.js`), and all of them when the history slider is dragged past now.
- Live updates: poll `/hazards` + `/reports` every 2 s; later WebSocket `ws://localhost:8000/ws` sends `{ type: tick|report|reset, changed: [hazards|roads|shelters|reports] }` → re-fetch only what's listed.
- Errors come back as `{ error, message }`.

**Not in the contract yet: ask Harsit to add these, build on your own fixture meanwhile:**
- History snapshots for the slider (hazards/roads at a past `sim_time`). Until then the dashboard records `/hazards` at each poll itself (`src/history.js`), so the slider only covers time the dashboard was open for; closed roads and routes aren't rewound yet.
- Priority residents list (fake generated data).
- Send notification (`POST /notifications`) + sent history.
- Report status (New / Verified / Dismissed) and updating it.
- Stats: people at risk, active reroutes.
- Relative humidity as a sim condition (e.g. `humidity_pct` 0–100 on `POST /sim/start`). The UI sends wind and humidity only; fuel dryness is left to the backend default. No temperature control.
- A `tornado` scenario: `POST /sim/start { scenario: "tornado", lat, lon, wind_kmh, wind_from_deg }`, the storm travelling with the wind, and `kind: "tornado"` hazard features. The dashboard fixture fakes it meanwhile.
## Rules
- Build exactly to `shared/contract.md`. Never edit it; ask Harsit (backend/lead) for changes.
- Features that need endpoints not in the contract yet (history snapshots, priority residents, notifications, report status): ask Harsit to add them, and build against a fixture in `shared/fixtures/` meanwhile.
- When `USE_FIXTURES` is true, load sample JSON from `shared/fixtures/` instead of calling the API.
- GeoJSON coordinates are always `[lon, lat]`.
- Updates: poll every 2 s for now; switch to the `/ws` WebSocket later (it signals "something changed", then re-fetch).
- Don't add dependencies without a reason; keep changes small.
- All code must be written during the event (natHacks rule).

## Step 0 (first PR)
Map of Edmonton, fetch `/hazards` and `/shelters` every 2 s and draw them, click the map to `POST /hazards`. Done when the growing fake fire circle shows up.

## Team
- Harsit: FastAPI backend, WebSocket, contract, merging PRs, pitch, live feed
- Azer: routing (road graph, closures, A*, shelter choice)
- Dviviz: wildfire model, then flood
- TechShriyaz: dashboard + phone web app
- Aarya: role TBD
