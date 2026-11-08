#!/usr/bin/env bash
# One command for the phone demo:
#   API + dashboard + phone  +  Cloudflare tunnels  +  QR join page
#
#   ./demo.sh
#
# Ctrl+C stops everything. Needs once: brew install cloudflared
# Laptop-only (no tunnels/QR): use ./dev.sh instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DEMO_DIR="$ROOT/.demo"
JOIN_HTML="$ROOT/demo-join.html"
JOIN_JSON="$ROOT/dashboard/public/demo-join.json"
JOIN_TXT="$DEMO_DIR/JOIN_URL.txt"
mkdir -p "$DEMO_DIR" "$ROOT/dashboard/public"
PHONE_LOG="$DEMO_DIR/cloudflared-phone.log"
API_LOG="$DEMO_DIR/cloudflared-api.log"
STACK_LOG="$DEMO_DIR/stack.log"

PIDS=()
PHONE_CF_PID=""
API_CF_PID=""
WROTE_JOIN=0

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

mark_join_stale() {
  # Old Cloudflare URLs die when tunnels stop — don't leave a scannable dead QR.
  if [[ "$WROTE_JOIN" == 1 || -f "$JOIN_HTML" || -f "$JOIN_JSON" ]]; then
    cat >"$JOIN_HTML" <<'HTML'
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" /><title>Shepherd — tunnels stopped</title>
<style>body{font-family:system-ui,sans-serif;max-width:28rem;margin:2rem auto;padding:0 1rem;color:#0B2545}
code{background:#EAF3FB;padding:2px 6px;border-radius:4px}</style></head>
<body>
<h1>Tunnels are stopped</h1>
<p>This QR / join link is <strong>dead</strong> (Cloudflare error 1033 if you scan an old one).</p>
<p>On the laptop run:</p>
<p><code>./demo.sh</code></p>
<p>Then scan the <em>new</em> QR it opens — quick-tunnel URLs change every run.</p>
</body></html>
HTML
    mkdir -p "$(dirname "$JOIN_JSON")"
    printf '%s\n' '{"active":false}' >"$JOIN_JSON"
    rm -f "$JOIN_TXT"
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
  for port in 8000 5173 5174; do
    kill_pids "$(port_pids "$port")" -KILL
  done
  mark_join_stale
  wait 2>/dev/null || true
  echo "Done. Run ./demo.sh again for a fresh QR (old links will not work)."
}
trap cleanup EXIT INT TERM

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing '$1'." >&2
    [[ "$1" == cloudflared ]] && echo "Install once:  brew install cloudflared" >&2
    exit 1
  fi
}

http_ok() {
  local url="$1" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 --max-time 2 "$url" 2>/dev/null || echo 000)"
  [[ "$code" =~ ^[23][0-9][0-9]$ ]]
}

wait_http() {
  local label="$1" i u
  shift
  local urls=("$@")
  for i in $(seq 1 120); do
    for u in "${urls[@]}"; do
      if http_ok "$u"; then
        echo "OK  $label"
        return 0
      fi
    done
    sleep 0.5
  done
  echo "Timed out waiting for $label (${urls[*]})" >&2
  echo "--- stack log (tail) ---" >&2
  tail -50 "$STACK_LOG" >&2 || true
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
  tail -40 "$log" >&2 || true
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
  echo "  python3 -m venv backend/.venv && source backend/.venv/bin/activate" >&2
  echo "  pip install -r backend/requirements.txt" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
# shellcheck disable=SC1091
source "$ROOT/scripts/ensure_backend_deps.sh"
ensure_backend_deps

[[ -d dashboard/node_modules ]] || (cd dashboard && npm install)
[[ -d phone/node_modules ]] || (cd phone && npm install)

if ! grep -q 'allowedHosts' phone/vite.config.js 2>/dev/null; then
  echo "WARN phone/vite.config.js missing allowedHosts — Cloudflare Host may be blocked." >&2
fi

# Kill stale join page / tunnels / ports before starting.
rm -f "$JOIN_HTML" "$JOIN_TXT"
pkill -f 'cloudflared tunnel --url http://127.0.0.1:5174' 2>/dev/null || true
pkill -f 'cloudflared tunnel --url http://127.0.0.1:8000' 2>/dev/null || true
free_port 8000
free_port 5173
free_port 5174

echo "Starting API + dashboard + phone…"
: >"$STACK_LOG"
: >"$DEMO_DIR/stack.pids"

uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000 >>"$STACK_LOG" 2>&1 &
PIDS+=("$!")

(cd dashboard && npm run dev) >>"$STACK_LOG" 2>&1 &
PIDS+=("$!")

(cd phone && npm run dev) >>"$STACK_LOG" 2>&1 &
PIDS+=("$!")

# Phone demo only needs API + phone. Dashboard is nice-to-have on the laptop.
wait_http "API :8000" "http://127.0.0.1:8000/health" "http://localhost:8000/health"
wait_http "Phone :5174" "http://127.0.0.1:5174/" "http://localhost:5174/"
if http_ok "http://127.0.0.1:5173/" || http_ok "http://localhost:5173/"; then
  echo "OK  Dashboard :5173"
else
  echo "WARN Dashboard :5173 not up yet — phone tunnels will still work. Check $STACK_LOG"
fi

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

# Build QR HTML + dashboard/public/demo-join.json (dashboard polls this).
python3 - "$JOIN_HTML" "$JOIN_JSON" "$PHONE_URL" "$API_URL" <<'PY'
import base64, json, sys, urllib.parse, urllib.request
out_html, out_json, phone, api = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/"), sys.argv[4].rstrip("/")
join = f"{phone}?api={urllib.parse.quote(api, safe='')}"
qr_data_url = None
try:
    q = urllib.parse.quote(join, safe="")
    png = urllib.request.urlopen(
        f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&ecc=M&data={q}",
        timeout=15,
    ).read()
    b64 = base64.b64encode(png).decode()
    qr_data_url = f"data:image/png;base64,{b64}"
    img = f'<img alt="QR" width="280" height="280" src="{qr_data_url}" />'
except Exception as exc:
    q = urllib.parse.quote(join, safe="")
    img = f'<img alt="QR" width="280" height="280" src="https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={q}" /><p>Embed failed: {exc}</p>'
html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Shepherd — join phone</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:28rem;margin:2rem auto;padding:0 1rem;color:#0B2545}}
code{{word-break:break-all;background:#EAF3FB;padding:2px 6px;border-radius:4px}}
.muted{{color:#3B5A7A}}.big{{font-size:1.05rem;font-weight:600}}
</style></head><body>
<h1>Shepherd phone</h1>
<p class="muted">Scan this QR (fresh for this <code>./demo.sh</code> run). Old QRs die when the script stops.</p>
<div>{img}</div>
<p class="big">Join URL</p>
<p><code>{json.dumps(join)[1:-1]}</code></p>
<p class="muted">API: <code>{json.dumps(api)[1:-1]}</code></p>
<p class="muted">Also shown on the dashboard at <code>http://localhost:5173</code>.</p>
</body></html>
"""
open(out_html, "w", encoding="utf-8").write(html)
payload = {"active": True, "joinUrl": join, "apiUrl": api, "phoneUrl": phone, "qrDataUrl": qr_data_url}
open(out_json, "w", encoding="utf-8").write(json.dumps(payload))
print(join)
PY
JOIN="$(python3 -c "import urllib.parse,sys; print(sys.argv[1].rstrip('/')+'?api='+urllib.parse.quote(sys.argv[2].rstrip('/'), safe=''))" "$PHONE_URL" "$API_URL")"
echo "$JOIN" >"$JOIN_TXT"
WROTE_JOIN=1

cat <<EOF

════════════════════════════════════════════════════════════
  FRESH join link (share this — not an old QR):

  $JOIN

  QR lives on the dashboard (right panel) — no browser popup.
  http://localhost:5173

  Also saved in:  $JOIN_TXT
  Fallback HTML:  $JOIN_HTML

  Ctrl+C stops everything (old links then show “tunnels stopped”).
════════════════════════════════════════════════════════════

EOF

wait
