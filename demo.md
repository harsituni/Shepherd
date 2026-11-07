# Shepherd demo — judge phones via QR

Goal: judges scan a QR, open the **phone** app, and talk to the **same** API as the dashboard.

## Option A — same Wi‑Fi (fastest)

1. On the laptop, start the stack:
   ```bash
   ./dev.sh
   ```
2. Find the laptop’s LAN IP (macOS):
   ```bash
   ipconfig getifaddr en0
   ```
   Example: `192.168.1.42`
3. Build a join page + QR (opens in your browser):
   ```bash
   ./scripts/demo_join.sh
   ```
   Or pass the IP explicitly:
   ```bash
   ./scripts/demo_join.sh --lan 192.168.1.42
   ```
4. Judges scan the QR → `http://<LAN-IP>:5174`  
   The phone auto-uses `http://<LAN-IP>:8000` as `API_URL` (same host, port 8000).

**Requirements:** phones on the same Wi‑Fi; no guest-network client isolation; mac firewall allows ports 8000 and 5174.

---

## Option B — public HTTPS (Cloudflare Tunnel)

Use this when phones are on cellular or a locked-down venue Wi‑Fi.

1. Install once: `brew install cloudflared`
2. Start Shepherd: `./dev.sh`
3. In **two** extra terminals:
   ```bash
   cloudflared tunnel --url http://127.0.0.1:5174
   # copy the https://….trycloudflare.com URL → PHONE_URL

   cloudflared tunnel --url http://127.0.0.1:8000
   # copy the https://….trycloudflare.com URL → API_URL
   ```
4. Make the QR (embeds `?api=` so the phone hits the API tunnel):
   ```bash
   ./scripts/demo_join.sh --tunnel "$PHONE_URL" "$API_URL"
   ```
5. Judges scan → phone UI over HTTPS, API over the second HTTPS tunnel.

### ngrok (alternative)

```bash
ngrok http 5174   # phone
ngrok http 8000   # API
./scripts/demo_join.sh --tunnel "$PHONE_URL" "$API_URL"
```

---

## How the phone picks the API

See `phone/src/config.js`:

| How you open the phone | API used |
|---|---|
| `http://localhost:5174` | `http://localhost:8000` |
| `http://<LAN-IP>:5174` | `http://<LAN-IP>:8000` |
| Tunnel URL with `?api=https://…` | that `api` value (saved in `localStorage`) |

Dashboard stays on the laptop (`http://localhost:5173` → `http://localhost:8000`).

---

## Sanity check

- Laptop: http://localhost:8000/health → `{"ok":true}`
- Phone: leave-by / route cards load; after “start evacuating”, dashboard can poll `GET /evacuees`
- Clear a stuck API override: DevTools → Application → Local Storage → delete `shepherd_api_url`
