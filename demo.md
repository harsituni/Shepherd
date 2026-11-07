# Shepherd demo — phones via QR

## One command

```bash
brew install cloudflared   # once
./demo.sh
```

That single script:

1. Frees ports 8000 / 5173 / 5174 if needed  
2. Starts API + dashboard + phone  
3. Opens two Cloudflare tunnels (phone UI + API)  
4. Writes `demo-join.html` with an embedded QR (`?api=` baked in)  
5. Prints a **join URL** to paste in team chat  

**Share the join URL / QR.** Any phone (Wi‑Fi or cellular) can open it.  
**Ctrl+C** stops the stack and the tunnels.

Dashboard for you: http://localhost:5173  

If you see **“Blocked request. This host is not allowed”**, pull a branch that has `allowedHosts: true` in `phone/vite.config.js` and re-run `./demo.sh`.

---

## Laptop only (no phones / no tunnels)

```bash
./dev.sh
```

---

## How the phone picks the API

`phone/src/config.js`:

| How you open the phone | API used |
|---|---|
| Join URL from `./demo.sh` (`?api=…`) | Cloudflare API tunnel |
| `http://localhost:5174` | `http://localhost:8000` |
| `http://<LAN-IP>:5174` | `http://<LAN-IP>:8000` |

Clear a stuck override: delete `localStorage` key `shepherd_api_url` for that origin.
