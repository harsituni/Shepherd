# shellcheck shell=bash
# Source after activating backend/.venv (from repo root).
# Installs shared requirements if routing/API imports are missing.
ensure_backend_deps() {
  if python -c "import fastapi, uvicorn, networkx, osmnx, sklearn" >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing backend Python deps (backend/requirements.txt)…"
  pip install -r backend/requirements.txt
  if ! python -c "import fastapi, uvicorn, networkx, osmnx, sklearn" >/dev/null 2>&1; then
    echo "Backend deps still missing after pip install. Check backend/requirements.txt." >&2
    return 1
  fi
}
