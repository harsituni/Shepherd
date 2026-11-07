// One place to point the phone app at the backend.
//
// Resolution order:
//   1. ?api=https://… on the page URL (also saved to localStorage) — for Cloudflare/ngrok
//   2. localStorage shepherd_api_url
//   3. Same host as this page, port 8000 — for LAN (open http://<laptop-ip>:5174)
//   4. VITE_API_URL or http://localhost:8000

function resolveApiUrl() {
  const fallback = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(
    /\/$/,
    '',
  )
  if (typeof window === 'undefined') return fallback

  const params = new URLSearchParams(window.location.search)
  const fromQuery = params.get('api')
  if (fromQuery) {
    const url = fromQuery.replace(/\/$/, '')
    try {
      localStorage.setItem('shepherd_api_url', url)
    } catch {
      /* private mode */
    }
    return url
  }

  try {
    const saved = localStorage.getItem('shepherd_api_url')
    if (saved) return saved.replace(/\/$/, '')
  } catch {
    /* ignore */
  }

  const host = window.location.hostname
  if (host && host !== 'localhost' && host !== '127.0.0.1') {
    // Tunnel hostnames are not the API — require ?api= (see demo.md).
    if (
      host.endsWith('trycloudflare.com') ||
      host.includes('ngrok-free.app') ||
      host.includes('ngrok.io')
    ) {
      return fallback
    }
    const proto = window.location.protocol === 'https:' ? 'https:' : 'http:'
    return `${proto}//${host}:8000`
  }

  return fallback
}

export const API_URL = resolveApiUrl()

// true = read shared/fixtures and fake the backend in memory; false = call API_URL.
export const USE_FIXTURES = false

export const MAP_CENTER = [-113.4938, 53.5461] // [lon, lat], downtown Edmonton
export const MAP_ZOOM = 11

export const POLL_MS = 2000
