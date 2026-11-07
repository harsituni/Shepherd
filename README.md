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
| Aarya | `dashboard/` |
| Shriyaz | `phone/` |

## Run it

**Backend** (from repo root)
```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate        # Windows: backend\.venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```
Check: http://localhost:8000/health · API docs: http://localhost:8000/docs

**Dashboard**
```bash
cd dashboard && npm install && npm run dev    # http://localhost:5173
```

**Phone**
```bash
cd phone && npm install && npm run dev        # http://localhost:5174
```

## How we work
- Read `AGENT_CONTEXT.md` and `shared/contract.md` first.
- Only edit your own folder. One branch per task (`phone/report-button`), small PR, squash merge into `main`.
- `main` must always run.
