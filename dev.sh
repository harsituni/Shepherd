#!/usr/bin/env bash
# Start API + dashboard + phone from the repo root.
# Frees port 8000 if something else is listening. Ctrl+C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PIDS=()

free_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Port $port in use (PID(s): $pids) — freeing it."
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.4
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Port $port still busy — force killing."
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.2
  fi
  if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Could not free port $port. Stop that process and retry."
    exit 1
  fi
}

cleanup() {
  echo
  echo "Stopping Shepherd…"
  local pid
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
    pkill -P "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ ! -f backend/.venv/bin/activate ]]; then
  echo "Missing backend/.venv. Create it once:"
  echo "  python3 -m venv backend/.venv"
  echo "  source backend/.venv/bin/activate"
  echo "  pip install -r backend/requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate

if [[ ! -d dashboard/node_modules ]]; then
  echo "Installing dashboard deps…"
  (cd dashboard && npm install)
fi
if [[ ! -d phone/node_modules ]]; then
  echo "Installing phone deps…"
  (cd phone && npm install)
fi

# 8000 is the usual conflict; also clear frontend ports so a second run works.
free_port 8000
free_port 5173
free_port 5174

echo "API        → http://localhost:8000  (docs: /docs)"
echo "Dashboard  → http://localhost:5173"
echo "Phone      → http://localhost:5174"
echo "Ctrl+C stops all."
echo

uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000 &
PIDS+=("$!")

(cd dashboard && npm run dev) &
PIDS+=("$!")

(cd phone && npm run dev) &
PIDS+=("$!")

wait
