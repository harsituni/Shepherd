# Shepherd

Live evacuation routing for Edmonton. Simulates wildfires (tornado simulation is in **beta**), closes roads in real time, and guides people to shelters on routes the hazard won't reach. Built at natHacks 2026.

- **Dashboard** (emergency managers): hazards, shelters, phone reports on a live map
- **Phone app** (public): safest route to a shelter, rerouted as hazards change
- **Backend** (FastAPI): state, hazard simulation, routing, evacuation traffic

## Layout
```
backend/
  api/       FastAPI app (main.py) + tests/
  routing/   road routing, traffic, map tools/ + tests/        → backend/routing/README.md
  sim/       wildfire sim (engine/, weatherpipe/), tornado (beta) + tests/  → backend/sim/README.md
  requirements.txt
dashboard/   Vite + React + MapLibre (port 5173)                → dashboard/CLAUDE.md
phone/       Vite + React + MapLibre (port 5174)                → phone/CLAUDE.md
shared/      contract.md + route_v3.md (the API), fixtures/ (example answers), gitVersion.mjs
docs/        judge study guide (.md, .tex source, .pdf)
scripts/     ensure_backend_deps.sh, demo_join.sh, demo_phone.sh
dev.sh       run everything locally
demo.sh      run everything + Cloudflare tunnels + a QR join page (see demo.md)
```
Visual rules for both apps: `DESIGN.md`. Product intent: `PRODUCT.md`.

## Team
| Person | Owns |
|---|---|
| Harsit | `backend/api`, `shared/`, integration, pitch |
| Azer | `backend/routing` |
| Dviviz | `backend/sim` |
| Shriyaz | `dashboard/` |
| Aarya | `phone/` |

## Run it

**One command** (API + dashboard + phone). Frees ports 8000 / 5173 / 5174 if needed; Ctrl+C stops all.
```bash
./dev.sh
```
Then open http://localhost:8000/health · http://localhost:5173 · http://localhost:5174

First time only: create the Python venv. `./dev.sh` and `./demo.sh` also run `pip install -r backend/requirements.txt` if routing deps (networkx/osmnx) are missing after a pull:
```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

**Or run pieces yourself**

Backend (from repo root):
```bash
source backend/.venv/bin/activate
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

Dashboard: `cd dashboard && npm install && npm run dev` → http://localhost:5173

Phone: `cd phone && npm install && npm run dev` → http://localhost:5174

## Tests
```bash
python -m pytest backend                        # all backend tests, from the repo root
cd phone && npx oxlint src && npx vite build
cd dashboard && npx oxlint src && npx vite build
```
Backend tests live in a `tests/` folder in each package (`backend/api/tests`, `backend/routing/tests`, `backend/sim/tests`).

## Demo / QR (judges + teammates on phones)

See **[demo.md](demo.md)**. One command (stack + Cloudflare tunnels + QR):

```bash
brew install cloudflared   # once
./demo.sh                  # share the printed join URL / QR page
```

Laptop-only (no tunnels): `./dev.sh`

## How we work
- Read this README and `shared/contract.md` first.
- Only edit your own folder. One branch per task (`phone/report-button`), small PR, squash merge into `main`.
- `main` must always run.
