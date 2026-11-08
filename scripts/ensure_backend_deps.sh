# shellcheck shell=bash
# Source after activating backend/.venv (from repo root).
# Installs shared requirements if routing/API/sim imports are missing.
ensure_backend_deps() {
  if python -c "import fastapi, uvicorn, networkx, osmnx, sklearn, rasterio" >/dev/null 2>&1; then
    :
  else
    echo "Installing backend Python deps (backend/requirements.txt)…"
    pip install -r backend/requirements.txt
    if ! python -c "import fastapi, uvicorn, networkx, osmnx, sklearn, rasterio" >/dev/null 2>&1; then
      echo "Backend deps still missing after pip install. Check backend/requirements.txt." >&2
      return 1
    fi
  fi
  # Road graph is gitignored; without it routing falls back to straight lines.
  local graph="backend/routing/data/edmonton_demo_drive.graphml"
  if [[ ! -f "$graph" ]]; then
    echo "Note: missing $graph — routes use straight-line backup until you run:"
    echo "  python -B -m backend.routing.prepare_graph --download"
  fi
}
