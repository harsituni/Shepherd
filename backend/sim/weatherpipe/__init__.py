"""Forecast weather → Contract A scenario files for the spread engine (backend.sim.engine).

No fire behaviour lives here. See conventions.py for the unit rules.

Demo (live, Edmonton):  python -m backend.sim.weatherpipe.demo backend/sim/scenarios/edm-demo-1.json --out contracts/
Demo replay (offline):  ... --source cache:latest
Single live build:      python -m backend.sim.weatherpipe.build backend/sim/scenarios/edm-demo-1.json --out runs/

Needs OPENWEATHER_API_KEY in the environment or the repo-root .env.
"""
