# Shepherd

Live evacuation routing for Edmonton. Simulates wildfires and floods, closes roads in real time, and guides people to shelters on routes the hazard won't reach. Built at natHacks 2026.

- **Dashboard** (emergency managers): hazards, shelters, phone reports on a live map
- **Phone app** (public): safest route to a shelter, rerouted as hazards change
- **Backend** (FastAPI): state, hazard simulation, routing

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

First time only: create the Python venv (script runs `npm install` for frontends if missing):
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

## Demo / QR (judges + teammates on phones)

See **[demo.md](demo.md)**. One command (stack + Cloudflare tunnels + QR):

```bash
brew install cloudflared   # once
./demo.sh                  # share the printed join URL / QR page
```

Laptop-only (no tunnels): `./dev.sh`

## How we work
- Read `AGENT_CONTEXT.md` and `shared/contract.md` first.
- Only edit your own folder. One branch per task (`phone/report-button`), small PR, squash merge into `main`.
- `main` must always run.
