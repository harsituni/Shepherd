// One place to point the phone app at the backend.
// For real phones on the same Wi-Fi, use the laptop's LAN IP, e.g. 'http://192.168.1.20:8000'.
export const API_URL = 'http://localhost:8000'

// true = read shared/fixtures and fake the backend in memory; false = call API_URL.
export const USE_FIXTURES = true

export const MAP_CENTER = [-113.4938, 53.5461] // [lon, lat], downtown Edmonton
export const MAP_ZOOM = 11

export const POLL_MS = 2000
