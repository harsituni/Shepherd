#!/usr/bin/env bash
# Build a local HTML page with a QR code for judges to open the phone app.
# Usage:
#   ./scripts/demo_join.sh                     # LAN: auto-detect IP
#   ./scripts/demo_join.sh --lan 172.28.92.160
#   ./scripts/demo_join.sh --tunnel PHONE_URL API_URL
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/demo-join.html"

lan_ip() {
  if [[ -n "${1:-}" ]]; then
    echo "$1"
    return
  fi
  local ip=""
  # Prefer common Wi‑Fi / Ethernet interfaces on macOS.
  local iface
  for iface in en0 en1 en2 en3 en4 en5; do
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    [[ -n "$ip" ]] && break
  done
  if [[ -z "$ip" ]]; then
    ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}' || true)"
  fi
  if [[ -z "$ip" ]]; then
    echo "Could not detect LAN IP. Pass it explicitly:" >&2
    echo "  ./scripts/demo_join.sh --lan YOUR_IP" >&2
    echo "Find it with: ipconfig getifaddr en0   (or ifconfig | grep 'inet ')" >&2
    exit 1
  fi
  echo "$ip"
}

check_lan() {
  local ip="$1"
  local ok=1
  if curl -sf --connect-timeout 2 "http://${ip}:8000/health" >/dev/null; then
    echo "OK  API reachable at http://${ip}:8000/health"
  else
    echo "FAIL API not reachable at http://${ip}:8000/health" >&2
    echo "     Is ./dev.sh running? Is this YOUR laptop IP (not an example from the docs)?" >&2
    ok=0
  fi
  if curl -sf --connect-timeout 2 -o /dev/null "http://${ip}:5174/"; then
    echo "OK  Phone UI reachable at http://${ip}:5174/"
  else
    echo "FAIL Phone UI not reachable at http://${ip}:5174/" >&2
    echo "     Start ./dev.sh first. Phone Vite must bind with host: true." >&2
    ok=0
  fi
  if [[ "$ok" != 1 ]]; then
    echo >&2
    echo "Refusing to write a QR for a URL that does not work from this machine." >&2
    exit 1
  fi
}

write_html() {
  local phone_url="$1"
  local api_url="${2:-}"
  python3 - "$OUT" "$phone_url" "$api_url" <<'PY'
import base64, json, sys, urllib.parse, urllib.request

out, phone, api = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3].rstrip("/")
join = phone
api_label = "(same host :8000 — phone derives this automatically on LAN)"
if api:
    join = f"{phone}?api={urllib.parse.quote(api, safe='')}"
    api_label = api

# Bake a PNG QR into the HTML so file:// works with no CDN / no JS.
qr_img = ""
qr_err = ""
try:
    q = urllib.parse.quote(join, safe="")
    png_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&ecc=M&data={q}"
    with urllib.request.urlopen(png_url, timeout=15) as resp:
        png = resp.read()
    b64 = base64.b64encode(png).decode("ascii")
    qr_img = f'<img alt="QR code" width="280" height="280" src="data:image/png;base64,{b64}" />'
except Exception as exc:
    qr_err = str(exc)
    q = urllib.parse.quote(join, safe="")
    qr_img = (
        f'<img alt="QR code" width="280" height="280" '
        f'src="https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={q}" />'
        f'<p class="muted">Embedded QR failed ({qr_err}). Showing live image (needs internet).</p>'
    )

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Shepherd — join phone</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 28rem; margin: 2rem auto; padding: 0 1rem; color: #0B2545; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
    p, code {{ font-size: 0.95rem; line-height: 1.4; }}
    code {{ word-break: break-all; background: #EAF3FB; padding: 2px 6px; border-radius: 4px; }}
    #qr {{ margin: 1.5rem 0; }}
    .muted {{ color: #3B5A7A; }}
    .big {{ font-size: 1.05rem; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>Shepherd phone</h1>
  <p class="muted">Scan the QR, or type the join URL on a phone on the <strong>same Wi‑Fi / VPN</strong> as this laptop.</p>
  <div id="qr">{qr_img}</div>
  <p class="big">Join URL</p>
  <p><code>{json.dumps(join)[1:-1]}</code></p>
  <p class="muted">API: <code>{json.dumps(api_label)[1:-1]}</code></p>
  <p class="muted">If the phone cannot connect, the laptop IP may be on a VPN (e.g. 172.x) that phones do not share — use Cloudflare Tunnel (see demo.md Option B).</p>
</body>
</html>
"""
open(out, "w", encoding="utf-8").write(html)
print(f"Wrote {out}")
print(f"Phone: {phone}")
print(f"API:   {api_label}")
print(f"Join:  {join}")
PY

  if command -v open >/dev/null 2>&1; then
    open "$OUT" 2>/dev/null || open -a Safari "$OUT" 2>/dev/null || \
      echo "Open $OUT in a browser to show the QR."
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$OUT" 2>/dev/null || echo "Open $OUT in a browser to show the QR."
  else
    echo "Open $OUT in a browser to show the QR."
  fi
}

case "${1:-}" in
  --tunnel)
    PHONE_URL="${2:-}"
    API_URL="${3:-}"
    if [[ -z "$PHONE_URL" || -z "$API_URL" ]]; then
      echo "Usage: ./scripts/demo_join.sh --tunnel PHONE_URL API_URL" >&2
      echo "See demo.md (Cloudflare Tunnel / ngrok)." >&2
      exit 1
    fi
    write_html "$PHONE_URL" "$API_URL"
    ;;
  --lan)
    IP="$(lan_ip "${2:-}")"
    echo "Using LAN IP: $IP"
    check_lan "$IP"
    write_html "http://${IP}:5174" ""
    ;;
  -h|--help)
    cat <<'HELP'
Usage:
  ./scripts/demo_join.sh
  ./scripts/demo_join.sh --lan YOUR_LAPTOP_IP
  ./scripts/demo_join.sh --tunnel PHONE_URL API_URL

Find your IP:  ipconfig getifaddr en0
Do not use example IPs from the docs (e.g. 192.168.1.42) unless that is really yours.
HELP
    ;;
  *)
    IP="$(lan_ip "${1:-}")"
    echo "Using LAN IP: $IP"
    check_lan "$IP"
    write_html "http://${IP}:5174" ""
    ;;
esac
