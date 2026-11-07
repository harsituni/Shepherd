# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

Both surfaces are web. The phone app is a web page laid out at ~390px that behaves like a mobile app, not a native app; judges open it on their own phones through a QR code.

## Users

- **Emergency managers / Government of Alberta officials** (dashboard, `dashboard/`). They sit at a desk during an incident, or run a drill, around Edmonton. Their job: simulate or monitor a wildfire or flood, see who is at risk, watch roads close and evacuees get rerouted, track high-priority residents, triage reports from the public, and push updates to every resident.
- **Residents of the affected area** (phone app, `phone/`). They are on a phone, possibly under stress, possibly already moving. Their job: get the safest route to an open shelter, understand why it changed, receive government updates, and report hazards or their own status (safe / need help).
- **Hackathon judges** (natHacks 2026, Defense & Security theme). They assess both surfaces in a short demo and on their own phones.

## Product Purpose

Shepherd is live evacuation routing for Edmonton. It simulates wildfires (main priority) and floods, closes roads in real time, and guides people to shelters on routes the hazard won't reach. The dashboard is the command view; the phone app is the public view; a FastAPI backend holds the shared state, runs the hazard sim and computes routes.

Success: it wins the demo, and every screen stays credible as something a real official or resident could actually use. A demo-only shortcut that would look fake to an emergency manager counts as a failure.

## Positioning

Routes are recalculated live around both the hazard's current extent and its *predicted* spread (T+30 / T+60), and officials and residents work from one shared live state. When the dashboard sees a road close, the phone reroutes within seconds and says why. A broadcast alert system or a static evacuation map can't truthfully claim that loop.

## Operating Context

- Live mode (real data feeds) vs Drill mode (simulation), switchable on the dashboard.
- The sim ticks every 2 s real time; both frontends poll the backend every 2 s, with a WebSocket "something changed" signal planned.
- The dashboard is used on a laptop or desktop; it must also stack cleanly on narrow screens. The phone app runs on judges' real phones on the same Wi-Fi as the backend laptop.
- Time is expressed as `sim_time` / T+minutes from scenario start.
- The API contract is `shared/contract.md` (owned by Harsit; never edited by frontend work). GeoJSON is `[lon, lat]`.

## Capabilities and Constraints

- **Dashboard** (priority order): disaster simulation with conditions (wind speed, wind direction, fuel dryness, relative humidity; river rise rate for flood; no temperature control), play/pause/reset, speed 1×/4×/16×; rerouting map with predicted path, closed roads, evacuation routes and shelters; a rerouting updates feed; a historical progression slider; high-priority residents (needs category, evacuation status); a "Notify all residents" composer with severity (Advisory / Alert / Evacuation order) and target area; reported hazards with status (New / Verified / Dismissed).
- **Dashboard key numbers, only these four:** people at risk, roads closed, active reroutes, shelter capacity used.
- **Phone** (priority order): best route from real-time data with auto-reroute and the reason for it; government notifications as a top banner plus a Gov updates tab; report hazard (fire, flooded road, blocked road), I'm safe, Need help; predicted hazard path on the map with a distance/direction line; survival tips per hazard type.
- Stack: Vite + React + `maplibre-gl` with an OpenStreetMap basemap; FastAPI backend; no database, auth or Docker; no new dependencies without a reason.
- Several features depend on endpoints that aren't in the contract yet (predicted path, history snapshots, priority residents, notifications, report status, people-at-risk / active-reroutes stats, humidity). These are built against fixtures in `shared/fixtures/` until the backend adds them.
- Team rule: each person edits only their own folder. Shriyaz owns `dashboard/` and `phone/`.
- All code must be written during the event (natHacks rule).

## Brand Commitments

- The name is **Shepherd**, used as Shepherd's own brand. Never use the Government of Alberta logo or wordmark.
- Tone: a calm, plain government service, modelled on Alberta.ca's wildfire pages.
- The team has already fixed binding visual constraints (palette, Public Sans, hazard-only orange, closed-road-only red, no gradients or emoji icons, and the full "looks AI-generated" ban list). They live in `dashboard/CLAUDE.md` and `phone/CLAUDE.md`, and those files are the authority.
- Approved layout mockups: `dashboard/design/dashboard-mockup.html` (+ `dashboardpic.png`) and `phone/design/phone-mockup.html` (+ `phone.png`). They are a visual reference only.

## Evidence on Hand

- Fixtures: `shared/fixtures/hazards.json`, `shelters.json`, `route.json`, `reports.json`, plus a live backend sim.
- Three hard-coded Edmonton shelters (from the contract).
- No real residents, testimonials, users or deployment exist. Priority residents are fake, generated demo data only and never real personal data. Every number on screen must come from the backend or a fixture; don't invent filler stats, endorsements or claims of official adoption.

## Product Principles

1. **One live truth.** Whatever the dashboard shows, the phone reflects within seconds; never let the two surfaces disagree.
2. **Explain every change.** A reroute, closure or alert always carries its reason and its time (T+min).
3. **Only real numbers.** Every figure traces to the backend or a fixture. Show fewer numbers rather than decorative ones.
4. **Credible under stress.** Design for an official mid-incident and a resident on the move: plain hierarchy, big targets, nothing that reads as a demo gimmick.
5. **Prediction is first-class.** The forecast spread informs routing and is shown as clearly as the hazard itself.

## Accessibility & Inclusion

- Touch targets ≥44px; text contrast ≥4.5:1 on both surfaces.
- Residents may be stressed, moving, or have mobility needs (the priority-residents feature exists for people who are disabled or have no vehicle). Phone copy should be short, direct and actionable.
