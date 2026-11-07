#!/usr/bin/env bash
# Start API + dashboard + phone from the repo root.
# Frees port 8000 if something else is listening. Ctrl+C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PIDS=()

WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;; esac

# PIDs listening on a TCP port (lsof on macOS/Linux, netstat on Windows Git Bash).
port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null | awk -v p=":$port" '$1=="TCP" && $2 ~ p"$" && $4=="LISTENING" {print $5}' | sort -u || true
  fi
}

kill_pids() {
  local pid
  for pid in $1; do
    if [[ "$WINDOWS" == 1 ]]; then
      taskkill //F //PID "$pid" >/dev/null 2>&1 || true
    else
      kill "$2" "$pid" 2>/dev/null || true
    fi
  done
}

free_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Port $port in use (PID(s): $pids) — freeing it."
  kill_pids "$pids" -TERM
  sleep 0.4
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    echo "Port $port still busy — force killing."
    kill_pids "$pids" -KILL
    sleep 0.2
  fi
  if [[ -n "$(port_pids "$port")" ]]; then
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

VENV_ACTIVATE=backend/.venv/bin/activate
[[ -f "$VENV_ACTIVATE" ]] || VENV_ACTIVATE=backend/.venv/Scripts/activate  # Windows
if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "Missing backend/.venv. Create it once:"
  echo "  python3 -m venv backend/.venv        (Windows: py -m venv backend/.venv)"
  echo "  source backend/.venv/bin/activate    (Windows: source backend/.venv/Scripts/activate)"
  echo "  pip install -r backend/requirements.txt"
  exit 1
fi
# shellcheck disable=SC1090
source "$VENV_ACTIVATE"

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
