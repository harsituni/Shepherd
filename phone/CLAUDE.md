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
2. **Government notifications.** Updates sent from the dashboard pop up as a banner at the top of the screen (slide down, tap to expand, dismissable). Colour by severity: Advisory (blue), Alert (dark blue), Evacuation order (orange). The persistent alert banner shows the most severe active one. Past updates live in the **Alerts** tab.
3. **Report hazards/events.** "Report hazard" opens a sheet: type (fire, flooded road, blocked road, other; `other` requires a note and is not in contract v1 yet, so ask Harsit to add it), uses your current location, optional note, submit → `POST /reports`. Also "I'm safe" and "Need help" buttons, which send the same endpoint and show up on the dashboard. Confirm with a short toast.
4. **Predicted path of the disaster.** On the map: the hazard now (solid orange) and its predicted spread as dashed rings labelled T+30 / T+60, plus "Fire is X km west of you, moving east" in the alert.

## Layout (matches the approved mockup)
- Mockup: `design/phone-mockup.html` (screenshot `design/phone.png`). Visual reference only; rebuild as React components with MapLibre in place of the sketched SVG map.
- Header in Alberta's brand dark blue `#005072`: a small placeholder logo (white square, navy crook; same as the dashboard) and "Shepherd" on the left, city name on the right, all vertically centred.
- Notification / alert banner directly under the header.
- Tabs: **Route** · **Alerts**. (The survival/safety tips tab was removed.)
- Route tab: map (taller until a location is set, then ~290px), map key, reroute notice, shelter + ETA line, next turn, Start navigation.
- The mockup predates the Alberta-style pass: where it differs (big ETA number, pill buttons, tinted notices), follow `/DESIGN.md`.
- Bottom bar, always visible: **Report hazard** · **I'm safe** · **Need help**.

## Design
- **Visual system: see `/DESIGN.md`** (shared with `dashboard/`; tokens, components, rules). If it and this section disagree, flag it rather than picking one.
- Minimalist, inspired by Alberta.ca's wildfire pages: plain blue and white, calm, big tap targets.
- Colours: header `#005072`, navy `#0B3D6E` (outline buttons, selected states, toast), blue `#0070C4` (primary, route, predicted path), tint `#EAF3FB` (alert banner only), borders `#D3E3F2`, text `#0B2545`, muted `#3B5A7A`.
- Gold `#FEBA35` only for the 3px keyboard focus ring (as on Alberta.ca).
- Orange `#D9480F` only for the hazard and evacuation-order alerts, red `#C62828` only for closed roads and the "Need help" button.
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
- `src/config.js` exports `API_URL` (default `http://localhost:8000`; use the laptop's LAN IP for real phones) and `USE_FIXTURES` (true until the backend is ready).

## API this app uses (from `shared/contract.md` v1)
- Backend `http://localhost:8000` (laptop LAN IP for real phones; backend runs with `--host 0.0.0.0`) · this app runs on port **5174** · map starts at `[-113.4938, 53.5461]`, zoom `11`.
- `GET /route?lat=&lon=` → `{ shelter_id, shelter_name, distance_km, eta_min, rerouted, reroute_reason, steps: [{ instruction, distance_km }], geometry: LineString }`. Show the reroute notice only when `rerouted` is true; `steps` may be `[]` (hide next turn). 404 `{ error: "no_route" }` → show "No safe shelter reachable, call 911".
- `GET /hazards`: draw `zone: core` solid orange, `buffer` lighter.
- `GET /shelters`: `occupancy / capacity` for "% full".
- `POST /reports` `{ kind, lat, lon, note? }`, `kind` = `fire`|`flooded_road`|`blocked_road` (Report hazard sheet), `safe` (I'm safe), `sos` (Need help). 201 → `{ id, received }` → toast.
- Live updates: poll `/route` every 2 s; later WebSocket `ws://localhost:8000/ws` → re-fetch on `changed`.
- Errors come back as `{ error, message }`.

**Not in the contract yet: ask Harsit to add these, build on your own fixture meanwhile:**
- Government notifications feed (`GET /notifications`: id, title, message, severity `advisory`|`alert`|`evacuation`, time) for pop-ups and the Alerts tab. Built against `shared/fixtures/notifications.json`; a 404 is treated as "no notifications".
- Predicted path (hazard features at T+30 / T+60).
- Distance/direction to the hazard for the alert banner (or compute it client-side from `/hazards`).

## Rules
- Build exactly to `shared/contract.md`. Never edit it; ask Harsit (backend/lead) for changes.
- Features that need endpoints not in the contract yet (government notifications, predicted path): ask Harsit to add them, and build against a fixture in `shared/fixtures/` meanwhile.
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
- Dviviz: wildfire model, then flood
- TechShriyaz: dashboard + phone web app
- Aarya: role TBD
