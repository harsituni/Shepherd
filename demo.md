# Shepherd demo — phones via QR

Judges and teammates open the **phone** app and hit the **same** API as your dashboard.

## One command (recommended)

On the host laptop:

```bash
./dev.sh                 # terminal 1 — API + dashboard + phone
./scripts/demo_phone.sh  # terminal 2 — Cloudflare tunnels + QR
```

`demo_phone.sh` will:

1. Wait for `:8000` and `:5174` (or start `./dev.sh` if they’re down)
2. Open two Cloudflare quick tunnels (phone UI + API)
3. Write `demo-join.html` with an **embedded QR** (`?api=` baked in)
4. Open that page and print a join URL to paste in chat

**Share the join URL / QR.** Anyone’s phone (Wi‑Fi or cellular) can use it.  
**Ctrl+C** in the `demo_phone.sh` terminal stops the tunnels.

Needs once: `brew install cloudflared`

If you see **“Blocked request. This host is not allowed”**, you’re on an old phone Vite config — pull this branch (`allowedHosts: true`) and restart `./dev.sh`.

---

## LAN only (same Wi‑Fi, no tunnel)

Only works when the phone can route to your laptop IP (often fails on VPN `172.x`):

```bash
./dev.sh
./scripts/demo_join.sh          # or: --lan YOUR_IP
```

Find your IP: `ipconfig getifaddr en0` — use **yours**, not a docs example.

---

## Manual tunnels (if you prefer)

```bash
./dev.sh
cloudflared tunnel --url http://127.0.0.1:5174   # → PHONE
cloudflared tunnel --url http://127.0.0.1:8000   # → API
./scripts/demo_join.sh --tunnel "$PHONE" "$API"
```

---

## How the phone picks the API

`phone/src/config.js`:

| How you open the phone | API used |
|---|---|
| `http://localhost:5174` | `http://localhost:8000` |
| `http://<LAN-IP>:5174` | `http://<LAN-IP>:8000` |
| Tunnel URL with `?api=https://…` | that `api` value (saved in `localStorage`) |

Dashboard stays on the laptop: http://localhost:5173 → http://localhost:8000

Stuck on a bad API override: clear `localStorage` key `shepherd_api_url` for that origin.
