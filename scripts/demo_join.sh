#!/usr/bin/env bash
# Build a local HTML page with a QR code for judges to open the phone app.
# Usage:
#   ./scripts/demo_join.sh                     # LAN: auto-detect IP
#   ./scripts/demo_join.sh --lan 192.168.1.42
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
  if command -v ipconfig >/dev/null 2>&1; then
    ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    [[ -z "$ip" ]] && ip="$(ipconfig getifaddr en1 2>/dev/null || true)"
  fi
  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "$ip" ]]; then
    echo "Could not detect LAN IP. Pass it: ./scripts/demo_join.sh --lan 192.168.x.x" >&2
    exit 1
  fi
  echo "$ip"
}

write_html() {
  local phone_url="$1"
  local api_url="${2:-}"
  python3 - "$OUT" "$phone_url" "$api_url" <<'PY'
import json, sys, urllib.parse
out, phone, api = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3].rstrip("/")
join = phone
api_label = "(same host :8000)"
if api:
    join = f"{phone}?api={urllib.parse.quote(api, safe='')}"
    api_label = api
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
    code {{ word-break: break-all; }}
    #qr {{ margin: 1.5rem 0; }}
    .muted {{ color: #3B5A7A; }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/qrcode@1.5.4/build/qrcode.min.js"></script>
</head>
<body>
  <h1>Shepherd phone</h1>
  <p class="muted">Scan to open the evacuee app (same API as the dashboard).</p>
  <div id="qr"></div>
  <p><strong>Join URL</strong><br /><code id="url"></code></p>
  <p class="muted">API: <code id="api"></code></p>
  <script>
    const joinUrl = {json.dumps(join)};
    const apiUrl = {json.dumps(api_label)};
    document.getElementById("url").textContent = joinUrl;
    document.getElementById("api").textContent = apiUrl;
    QRCode.toCanvas(document.createElement("canvas"), joinUrl, {{ width: 280, margin: 2 }}, (err, canvas) => {{
      if (err) {{ document.getElementById("qr").textContent = String(err); return; }}
      document.getElementById("qr").appendChild(canvas);
    }});
  </script>
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
    write_html "http://${IP}:5174" ""
    ;;
  -h|--help)
    cat <<'HELP'
Usage:
  ./scripts/demo_join.sh
  ./scripts/demo_join.sh --lan 192.168.1.42
  ./scripts/demo_join.sh --tunnel PHONE_URL API_URL
HELP
    ;;
  *)
    IP="$(lan_ip "${1:-}")"
    write_html "http://${IP}:5174" ""
    ;;
esac
