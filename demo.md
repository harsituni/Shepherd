# Shepherd demo — judge phones via QR

Goal: judges scan a QR, open the **phone** app, and talk to the **same** API as the dashboard.

## Option A — same Wi‑Fi (fastest)

1. On the laptop, start the stack:
   ```bash
   ./dev.sh
   ```
2. Find **your** laptop LAN IP (do not copy an example from docs):
   ```bash
   ipconfig getifaddr en0
   ```
   Right now on many campus/VPN networks this looks like `172.x.x.x`, not `192.168.x.x`.
3. Confirm that IP works **from the laptop** before involving a phone:
   ```bash
   curl -s http://YOUR_IP:8000/health    # {"ok":true}
   open http://YOUR_IP:5174              # phone UI in the browser
   ```
4. Build the join page + QR (script checks reachability, embeds the QR as a PNG):
   ```bash
   ./scripts/demo_join.sh
   ```
   Or:
   ```bash
   ./scripts/demo_join.sh --lan YOUR_IP
   ```
   Open `demo-join.html` if it does not pop up. You should see a QR image and the join URL.
5. On a phone on the **same network as the laptop**, scan the QR or type that exact join URL.

**Requirements:** phone and laptop on the same Wi‑Fi/VPN; no guest-network client isolation; macOS Firewall allows incoming for Python/Node (or turn firewall off briefly).

**If the phone browser spins forever:** your laptop IP is often on a VPN (`172.x`) that phones are not on. Use Option B (tunnel) instead.

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

If the phone shows **“Blocked request. This host is not allowed”**, restart `./dev.sh` after pulling — `phone/vite.config.js` must have `server.allowedHosts: true`.

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
