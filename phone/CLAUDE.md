# Shepherd web app: CLAUDE.md

Owner: TechShriyaz (also owns `dashboard/`). Only edit files in `phone/` unless told otherwise.

## What this is
The public-facing Shepherd "app". It is NOT a native app: it's a web page laid out at phone width that acts like a mobile app. Judges open it on their own phones via a QR code. Part of the natHacks 2026 project (Defense & Security theme). The government side is the dashboard in `dashboard/`.

## Features (in priority order)
1. **Best-route map from real-time data.**
   - Set your location (tap the map or pick a preset).
   - Draw the safest route to a shelter from `GET /route`; auto-reroute whenever hazards or closed roads change.
   - Show a reroute notice with the reason ("Rerouted: Stony Plain Rd closed and fire heading toward 149 St").
   - Below the map: a map key, then the shelter name and one line "**ETA** · distance · % full", next turn, "Start navigation".
2. **Government notifications.** Updates sent from the dashboard pop up as a banner at the top of the screen (slide down, tap to expand, dismissable). Colour by severity: Advisory (blue), Alert (deep yellow `#9A6B00`), Evacuation order (deep red `#8A2F06`). The persistent alert banner shows the most severe active one. Past updates live in the **Alerts** tab.
3. **Report hazards/events.** The rail's Report button asks "Where is the hazard?": a teardrop pin drops in the middle of the map; drag it (or tap the map) to the incident and press "Drop pin here". A sheet then takes the type (fire, blocked road, other; `other` requires a message) and a message for emergency personnel of up to 30 characters (sent as `note`; never shown on the public map), with "Move pin" to go back; submit → `POST /reports` at the pin. Every phone polls `GET /reports` and draws the hazard kinds (not safe/sos, which stay responder-only) as white circles with an orange symbol per kind (`src/reportKinds.js`); tap one for its details. Also "I'm safe" and "Need help" buttons, which send the same endpoint and show up on the dashboard. Confirm with a short toast.
4. **Predicted path of the disaster.** On the map: the hazard now (solid orange) and its predicted spread as a single red dotted ring (no fill) labelled T+60, from `GET /forecast`, plus "Fire is X km west of you, moving east" in the alert. Each wildfire also gets an **evacuation zone** (a perfect circle centred on the current fire, reaching 1 km past its farthest edge; never the predicted path; yellow diagonal stripes, solid darker-yellow border), and a shelter the fire is in or forecast to come within that 1 km of turns **red**; tapping it shows its pop-up in red: capacity, then "Unsafe: Find another shelter". Same rule as the dashboard (`src/evacuation.js`).

## Layout: map-first (like a scooter app)
- References: `design/LIME-MapView_Device_UK-London.png` and `design/Screenshot 2026-11-07 174454.png` (Lime and Bird). The older stacked mockup (`design/phone-mockup.html`, `design/phone.png`) is superseded for layout; colours and type are unchanged.
- One screen, `src/components/MapScreen.jsx`: the map fills the screen and every control floats over it.
- **Top left:** area chip (Shepherd mark + place name). **Top right:** the alert / evacuation card, compact (headline only, e.g. "Wildfire evacuation / No deadline yet") with a small chevron; tapping it opens it to full width with the detail lines.
- **Right rail** (riding just above the route panel; hidden while the route panel is open, to avoid clutter): **Alerts** (official alerts sheet, with the build version at its foot), **Key** (map key sheet), **Report** (report sheet), **Priority** (register an Alberta disability ID so the dashboard marks you as a priority resident; only the ID type and last 4 characters are sent, `POST /priority`, not in the contract yet). No Safe button.
- **Bottom:** the route panel: shelter route cards you swipe sideways (only the card row scrolls, only sideways; selected = navy border wrapping the whole card; no "no fire forecast" line, and blocked cards just say "Fire forecast on this route"), drive mode + Start evacuating, the "location shared" line, and a subtle × floating just above the panel's corner that closes it to a one-line strip ("Shelter · 13 min · 5.1 km", tap to reopen and it slides up; a new location reopens it). The panel opens at that same height with a "Route details" heading peeking at the bottom; scroll the panel down for shelter spaces, trip, fire forecast, directions and notes. The "Clear" status is green (`--clear` #1E7B34). Under it, a full-width red **Need help** bar.
- No visible em dashes in UI copy.

## Design
- **Visual system: see `/DESIGN.md`** (shared with `dashboard/`; tokens, components, rules). If it and this section disagree, flag it rather than picking one.
- Minimalist, inspired by Alberta.ca's wildfire pages: plain blue and white, calm, big tap targets.
- Colours: header `#005072`, navy `#0B3D6E` (outline buttons, selected states, toast), blue `#0070C4` (primary, route), tint `#EAF3FB` (alert banner only), borders `#D3E3F2`, text `#0B2545`, muted `#3B5A7A`.
- Gold `#FEBA35` only for the 3px keyboard focus ring (as on Alberta.ca).
- Orange `#D9480F` only for the hazard and evacuation-order alerts, red `#C62828` only for closed roads (solid), the predicted path (dotted) and the "Need help" button.
- Font: **Public Sans** (Google Fonts, weights 400/500/600/700), fallback `system-ui, sans-serif`. Use `font-variant-numeric: tabular-nums` for ETA and distances. Type scale 14/16/18/20px (16 default, nothing under 14); no uppercase eyebrow labels.
- Corners: 6px (8px for cards and the pop-up). No pills; use a segmented control for small option sets. Flat surfaces separated by 1px borders; one soft shadow only on the pop-up notification.
- One solid button per area; others are navy outlines. Disabled controls get a flat style, never `opacity`. "Need help" is never disabled.
- Phone width ~390px, mobile-first, touch targets ≥44px, contrast ≥4.5:1.
- Must look right on a real phone on the same Wi-Fi.
- Don't use the Government of Alberta logo or wordmark; this is Shepherd's own branding.

## Don't (looks AI-generated)
- No Inter, Roboto, Poppins, Montserrat, DM Sans, Manrope, Space Grotesk, Plus Jakarta Sans, Geist, Outfit or any other default "AI website" font. Public Sans only.
- No gradients of any kind: no gradient backgrounds, buttons, text or glows. Solid colours only.
- No emoji as icons; use simple inline stroke SVG icons.
- No glassmorphism/blur, neon glows, coloured left-border accent cards, oversized rounded "bubble" cards or bouncy animations.
- No filler text or fake stats; every number comes from the backend or a fixture.
- Keep it looking like a calm, clean government service: white background, navy/blue accents, plain hierarchy.

## Stack
- Vite + React + `maplibre-gl`, OpenStreetMap basemap, GeoJSON layers.
- Own `package.json` inside `phone/`.
- `src/config.js` exports `API_URL` (default `http://localhost:8000`; use the laptop's LAN IP for real phones) and `USE_FIXTURES` (false: call the API; true: an in-memory stand-in built from `shared/fixtures/`).

## API this app uses (from `shared/contract.md` v1)
- Backend `http://localhost:8000` (laptop LAN IP for real phones; backend runs with `--host 0.0.0.0`) · this app runs on port **5174** · map starts at `[-113.4938, 53.5461]`, zoom `11`.
- `GET /route?lat=&lon=&check_route_id=` (v3, see `shared/route_v3.md`): 2 to 4 `options` with stable ids, `best_route_id` (null when nothing is safe or confirmable), `route_status`, `no_safe_route`. Only `ok`/`tight` options can be picked; `blocked`/`indeterminate` are greyed. Send the picked id as `check_route_id` on every poll. The best option is also copied to the top level (the v1 fields below).
- v1 fields: `{ shelter_id, shelter_name, distance_km, eta_min, rerouted, reroute_reason, steps: [{ instruction, distance_km }], geometry: LineString }`. Show the reroute notice only when `rerouted` is true; `steps` may be `[]` (hide next turn). 404 `{ error: "no_route" }` → show "No safe shelter reachable, call 911".
- `GET /hazards`: draw `zone: core` solid orange, `buffer` lighter.
- `GET /shelters`: `occupancy / capacity` for "% full".
- `GET /forecast` (contract v2): `outlines` at `t_min` 15, 30 … 120 minutes from now; only the 60 min one is drawn as the predicted path (merged into the hazards as `predicted_min` features in `src/api.js`). Empty when idle.
- `POST /evacuees` (contract v2) `{ id, lat, lon, route_id, route_status, shelter_id }`: a heartbeat every ~2 s from the moment a location is set (map tap, preset or Need help) and while evacuating, so the dashboard marks the phone. Route fields are null until a route is shown; the id is one per phone (`src/evacuate.js`). While it is sharing, a quiet line under the map says "Your location is shared with responders." (14px Slate Faint, no icon).
- `POST /reports` `{ kind, lat, lon, note? }`, `kind` = `fire`|`blocked_road`|`other` (Report hazard sheet), `safe` (I'm safe), `sos` (Need help). 201 → `{ id, received }` → toast.
- Live updates: poll `/route` every 2 s; later WebSocket `ws://localhost:8000/ws` → re-fetch on `changed`.
- Errors come back as `{ error, message }`.

- `GET /notifications`: id, title, message, severity `advisory`|`alert`|`evacuation`, time; pop-ups and the Alerts tab. A 404 is treated as "no notifications".
- Distance/direction to the hazard for the alert banner is computed client-side from `/hazards` and `/forecast` (`src/geo.js`).
- Tornado simulation is a **beta** feature: its alert banner and evacuation card say "(beta)".

## Rules
- Build exactly to `shared/contract.md`. Never edit it; ask Harsit (backend/lead) for changes.
- Features that need endpoints not in the contract yet: ask Harsit to add them, and build against a fixture in `shared/fixtures/` meanwhile.
- When `USE_FIXTURES` is true, load sample JSON from `shared/fixtures/` instead of calling the API.
- GeoJSON coordinates are always `[lon, lat]`.
- Updates: poll every 2 s for now; switch to the `/ws` WebSocket later, then re-fetch the route and notifications on change.
- Don't add dependencies without a reason; keep changes small.
- All code must be written during the event (natHacks rule).

## Step 0 (first PR)
Map of Edmonton, tap to set location, fetch `GET /route?lat=&lon=`, draw the returned LineString. Done when a line to a shelter appears.

## Team
- Harsit: FastAPI backend, WebSocket, contract, merging PRs, pitch, live feed
- Azer: routing (road graph, closures, A*, shelter choice)
- Dviviz: wildfire model
- TechShriyaz: dashboard + phone web app
- Aarya: role TBD
