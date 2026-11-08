# shellcheck shell=bash
# Source after activating backend/.venv (from repo root).
# Installs shared requirements if routing/API imports are missing.
ensure_backend_deps() {
  if python -c "import fastapi, uvicorn, networkx, osmnx, sklearn" >/dev/null 2>&1; then
    :
  else
    echo "Installing backend Python deps (backend/requirements.txt)…"
    pip install -r backend/requirements.txt
    if ! python -c "import fastapi, uvicorn, networkx, osmnx, sklearn" >/dev/null 2>&1; then
      echo "Backend deps still missing after pip install. Check backend/requirements.txt." >&2
      return 1
    fi
  fi
  # Prefer unpacked GraphML; otherwise the shipped .gz is enough for load_graph().
  local graph="backend/routing/data/edmonton_demo_drive.graphml"
  local graph_gz="backend/routing/data/edmonton_demo_drive.graphml.gz"
  if [[ ! -f "$graph" && ! -f "$graph_gz" ]]; then
    echo "Note: missing road graph — routes use straight-line backup until you add:"
    echo "  $graph_gz  (shipped) or run: python -B -m backend.routing.prepare_graph --download"
  fi
}
