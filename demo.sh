#!/usr/bin/env bash
# One command for the phone demo:
#   API + dashboard + phone  +  Cloudflare tunnels  +  QR join page
#
#   ./demo.sh
#
# Ctrl+C stops everything. Needs once: brew install cloudflared
#
# Laptop-only (no tunnels/QR): use ./dev.sh instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DEMO_DIR="$ROOT/.demo"
mkdir -p "$DEMO_DIR"
PHONE_LOG="$DEMO_DIR/cloudflared-phone.log"
API_LOG="$DEMO_DIR/cloudflared-api.log"
STACK_LOG="$DEMO_DIR/stack.log"

PIDS=()
PHONE_CF_PID=""
API_CF_PID=""

WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;; esac

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
  [[ -z "$pids" ]] && return 0
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
    echo "Could not free port $port. Stop that process and retry." >&2
    exit 1
  fi
}

cleanup() {
  echo
  echo "Stopping Shepherd demo (stack + tunnels)…"
  [[ -n "${PHONE_CF_PID}" ]] && kill "$PHONE_CF_PID" 2>/dev/null || true
  [[ -n "${API_CF_PID}" ]] && kill "$API_CF_PID" 2>/dev/null || true
  pkill -f 'cloudflared tunnel --url http://127.0.0.1:5174' 2>/dev/null || true
  pkill -f 'cloudflared tunnel --url http://127.0.0.1:8000' 2>/dev/null || true
  local pid
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
    pkill -P "$pid" 2>/dev/null || true
  done
  # Ports we own — clear leftovers (uvicorn reloader / vite children).
  for port in 8000 5173 5174; do
    kill_pids "$(port_pids "$port")" -TERM
  done
  wait 2>/dev/null || true
  echo "Done. Re-open demo-join.html later only if tunnels are running again."
}
trap cleanup EXIT INT TERM

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing '$1'." >&2
    [[ "$1" == cloudflared ]] && echo "Install once:  brew install cloudflared" >&2
    exit 1
  fi
}

wait_http() {
  local url="$1" label="$2" i
  for i in $(seq 1 90); do
    if curl -sf --connect-timeout 1 -o /dev/null "$url"; then
      echo "OK  $label"
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for $label ($url)" >&2
  echo "--- stack log (tail) ---" >&2
  tail -40 "$STACK_LOG" >&2 || true
  exit 1
}

wait_tunnel_url() {
  local log="$1" label="$2" i url
  for i in $(seq 1 90); do
    url="$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$log" 2>/dev/null | head -1 || true)"
    if [[ -n "$url" ]]; then
      echo "$url"
      return 0
    fi
    sleep 0.4
  done
  echo "Timed out waiting for $label tunnel. Log: $log" >&2
  tail -30 "$log" >&2 || true
  exit 1
}

need_cmd curl
need_cmd cloudflared
need_cmd python3
need_cmd npm

VENV_ACTIVATE=backend/.venv/bin/activate
[[ -f "$VENV_ACTIVATE" ]] || VENV_ACTIVATE=backend/.venv/Scripts/activate
if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "Missing backend/.venv. Create it once:" >&2
  echo "  python3 -m venv backend/.venv" >&2
  echo "  source backend/.venv/bin/activate" >&2
  echo "  pip install -r backend/requirements.txt" >&2
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

if ! grep -q 'allowedHosts' phone/vite.config.js 2>/dev/null; then
  echo "WARN phone/vite.config.js missing allowedHosts — Cloudflare Host may be blocked." >&2
fi

# Clear ports / old tunnels so this run owns everything.
pkill -f 'cloudflared tunnel --url http://127.0.0.1:5174' 2>/dev/null || true
pkill -f 'cloudflared tunnel --url http://127.0.0.1:8000' 2>/dev/null || true
free_port 8000
free_port 5173
free_port 5174

echo "Starting API + dashboard + phone…"
: >"$STACK_LOG"
(
  uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000 &
  echo $! >>"$DEMO_DIR/stack.pids"
  (cd dashboard && npm run dev) &
  echo $! >>"$DEMO_DIR/stack.pids"
  (cd phone && npm run dev) &
  echo $! >>"$DEMO_DIR/stack.pids"
  wait
) >>"$STACK_LOG" 2>&1 &
PIDS+=("$!")

wait_http "http://127.0.0.1:8000/health" "API :8000"
wait_http "http://127.0.0.1:5173/" "Dashboard :5173"
wait_http "http://127.0.0.1:5174/" "Phone :5174"

: >"$PHONE_LOG"
: >"$API_LOG"
echo "Starting Cloudflare tunnels…"
cloudflared tunnel --url http://127.0.0.1:5174 >"$PHONE_LOG" 2>&1 &
PHONE_CF_PID=$!
cloudflared tunnel --url http://127.0.0.1:8000 >"$API_LOG" 2>&1 &
API_CF_PID=$!

PHONE_URL="$(wait_tunnel_url "$PHONE_LOG" phone)"
API_URL="$(wait_tunnel_url "$API_LOG" api)"
echo "OK  Phone tunnel: $PHONE_URL"
echo "OK  API tunnel:   $API_URL"

"$ROOT/scripts/demo_join.sh" --tunnel "$PHONE_URL" "$API_URL"

JOIN="${PHONE_URL}?api=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$API_URL")"

cat <<EOF

════════════════════════════════════════════════════════════
  ONE LINK for teammates / judges (also in demo-join.html):

  $JOIN

  Dashboard (this laptop only): http://localhost:5173
  Ctrl+C stops API, frontends, and tunnels.
════════════════════════════════════════════════════════════

EOF

# Stay alive until interrupted.
wait
