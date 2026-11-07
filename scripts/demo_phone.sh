#!/usr/bin/env bash
# One-shot: make the Shepherd phone app reachable on real phones via HTTPS + QR.
#
#   ./scripts/demo_phone.sh
#
# What it does:
#   1. Checks (or starts) API :8000 + phone Vite :5174
#   2. Starts two Cloudflare quick tunnels
#   3. Writes demo-join.html with an embedded QR (?api= baked in)
#   4. Opens the QR page
#   5. Ctrl+C stops the tunnels (and the stack only if this script started it)
#
# Needs: brew install cloudflared
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DEMO_DIR="$ROOT/.demo"
mkdir -p "$DEMO_DIR"
PHONE_LOG="$DEMO_DIR/cloudflared-phone.log"
API_LOG="$DEMO_DIR/cloudflared-api.log"
STACK_PID=""
PHONE_CF_PID=""
API_CF_PID=""
STARTED_STACK=0

cleanup() {
  echo
  echo "Stopping Cloudflare tunnels…"
  [[ -n "${PHONE_CF_PID}" ]] && kill "$PHONE_CF_PID" 2>/dev/null || true
  [[ -n "${API_CF_PID}" ]] && kill "$API_CF_PID" 2>/dev/null || true
  # Also clear any orphaned quick tunnels we may have launched.
  pkill -f 'cloudflared tunnel --url http://127.0.0.1:5174' 2>/dev/null || true
  pkill -f 'cloudflared tunnel --url http://127.0.0.1:8000' 2>/dev/null || true
  if [[ "$STARTED_STACK" == 1 && -n "$STACK_PID" ]]; then
    echo "Stopping Shepherd stack started by this script…"
    kill "$STACK_PID" 2>/dev/null || true
    pkill -P "$STACK_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  echo "Done. (demo-join.html is left in the repo root for reference.)"
}
trap cleanup EXIT INT TERM

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing '$1'." >&2
    if [[ "$1" == cloudflared ]]; then
      echo "Install once:  brew install cloudflared" >&2
    fi
    exit 1
  fi
}

local_up() {
  curl -sf --connect-timeout 1 "http://127.0.0.1:8000/health" >/dev/null 2>&1 \
    && curl -sf --connect-timeout 1 -o /dev/null "http://127.0.0.1:5174/" >/dev/null 2>&1
}

wait_local() {
  local i
  echo "Waiting for API :8000 and phone :5174…"
  for i in $(seq 1 60); do
    if local_up; then
      echo "OK  localhost:8000 + localhost:5174"
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for the stack. Start it yourself with ./dev.sh and re-run." >&2
  exit 1
}

wait_tunnel_url() {
  local log="$1"
  local label="$2"
  local i url
  for i in $(seq 1 90); do
    url="$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$log" 2>/dev/null | head -1 || true)"
    if [[ -n "$url" ]]; then
      echo "$url"
      return 0
    fi
    sleep 0.4
  done
  echo "Timed out waiting for $label tunnel URL. Log: $log" >&2
  tail -20 "$log" >&2 || true
  exit 1
}

need_cmd curl
need_cmd cloudflared
need_cmd python3

# --- stack ---
if local_up; then
  echo "OK  Shepherd already running on :8000 and :5174"
else
  if [[ ! -x ./dev.sh ]]; then
    echo "Stack is down and ./dev.sh is missing. Start the API + phone, then re-run." >&2
    exit 1
  fi
  echo "Starting ./dev.sh in the background…"
  ./dev.sh >"$DEMO_DIR/dev.log" 2>&1 &
  STACK_PID=$!
  STARTED_STACK=1
  wait_local
fi

# Warn if phone Vite might still block tunnel hosts (old checkout).
if ! grep -q 'allowedHosts' phone/vite.config.js 2>/dev/null; then
  echo "WARN phone/vite.config.js has no allowedHosts — tunnel Host header may be blocked." >&2
  echo "     Pull/merge the issue-52 branch (allowedHosts: true), then restart ./dev.sh." >&2
fi

# --- fresh tunnels ---
pkill -f 'cloudflared tunnel --url http://127.0.0.1:5174' 2>/dev/null || true
pkill -f 'cloudflared tunnel --url http://127.0.0.1:8000' 2>/dev/null || true
sleep 0.3
: >"$PHONE_LOG"
: >"$API_LOG"

echo "Starting Cloudflare tunnel → phone :5174 …"
cloudflared tunnel --url http://127.0.0.1:5174 >"$PHONE_LOG" 2>&1 &
PHONE_CF_PID=$!

echo "Starting Cloudflare tunnel → API :8000 …"
cloudflared tunnel --url http://127.0.0.1:8000 >"$API_LOG" 2>&1 &
API_CF_PID=$!

PHONE_URL="$(wait_tunnel_url "$PHONE_LOG" phone)"
API_URL="$(wait_tunnel_url "$API_LOG" api)"
echo "OK  Phone tunnel: $PHONE_URL"
echo "OK  API tunnel:   $API_URL"

# --- QR ---
"$ROOT/scripts/demo_join.sh" --tunnel "$PHONE_URL" "$API_URL"

JOIN="${PHONE_URL}?api=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$API_URL")"

cat <<EOF

════════════════════════════════════════════════════════
  Share this with teammates / judges (scan the QR page):

  $JOIN

  Dashboard stays on this laptop: http://localhost:5173
  Ctrl+C here stops the tunnels.
════════════════════════════════════════════════════════

EOF

# Keep tunnels alive until Ctrl+C.
wait "$PHONE_CF_PID" "$API_CF_PID"
