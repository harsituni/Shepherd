# Shepherd -- 1-Page Judge Card

**Pitch:** Shepherd is a live evacuation system for Edmonton that routes people to safe shelters on real roads as a wildfire or tornado spreads with the wind -- and keeps re-routing them when roads jam or become unsafe.

**Vision:** Static "leave west" fails when fire, wind, and traffic change. Commanders get a live map; residents get a phone route that updates mid-trip -- hazard grows with wind, roads close early, demand is estimated, phones reroute away from fire and gridlock.

## Tools & why
| Tool | Why |
|------|-----|
| FastAPI | JSON API; in-memory (no DB/auth) |
| React + Vite | Dashboard :5173 + phone :5174 |
| MapLibre + OSM | Free maps; GeoJSON [lon, lat] |
| OSMnx / NetworkX | Real Edmonton drive graph |
| SciPy / NumPy / Shapely | Dijkstra, BPR, fire geometry |
| OpenWeather + wind sim | Spread + forecast outlines |
| Cloudflare (`./demo.sh`) | QR join for judges |

## How it works
1. **Hazard:** wildfire/tornado + wind; sim `T+N`; forecast (T+60).
2. **Road rule:** close at **`arrival_min - 30`**. Routes: **ok** (60+ min) / **tight** / **blocked**.
3. **Phone:** snap to OSM -> open shelter -> poll ~2s -> `shouldReroute` mid-trip.
4. **Traffic:** BPR delay; anti-gridlock. Up to **100k cars** via projection (~2.5k agents x weight). Demand = pin + zone density + day/time.
5. **Commander:** closed roads, traffic ribbons, live blue phone routes, cut-off banner.

**Demo:** 1x wildfire -> pin near phone -> Play -> fire/closes/reroute toast -> cut-off banner. Reset clears traffic. Edmonton ~ -113.5, 53.5.

## Curveballs
| Question | Answer |
|----------|--------|
| Production / life-safety? | Prototype, not certified. Clear margin + real OSM; needs agency validation, auth, persistence. |
| Where do 100k cars come from? | Zone density x footprint x daypart -> people -> cars; projected onto fewer agents for realtime. |
| Why not Google/Waze? | Hazard-timed closures, shelter safety, commander + public state in one loop. |
| Why partial colouring? | Only actionable layers: fire, closed, jam, active routes. |
| Flood / other? | Flood deferred; same architecture extends. |
| Fire model accuracy? | Wind-driven demo/forecast, not firefighting product; routing uses `arrival_min`. |
| Privacy? | No auth; temporary pins; priority = type + last 4. |
| What's novel? | Wind hazard -> timed closures -> live phone reroute -> commander cut-offs on real Edmonton OSM. |
| Next? | Census demand, websockets, agency roles, live shelter intake. |

*If you freeze:* restate pitch -> point fire / closed roads / blue route -> one reroute -> "happy to go deeper on routing, traffic, or demand."

(PDF built from `Shepherd_Judge_Study_Guide.tex`)
