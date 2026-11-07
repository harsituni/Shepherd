import { API_URL, USE_FIXTURES } from './config.js'
import { distanceKm, ringCentroid } from './geo.js'
import hazardsFixture from '../../shared/fixtures/hazards.json'
import sheltersFixture from '../../shared/fixtures/shelters.json'
import notificationsFixture from '../../shared/fixtures/notifications.json'

// ---------- real backend ----------

async function request(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = new Error(body?.message ?? `HTTP ${res.status}`)
    err.code = body?.error ?? 'http_error'
    err.status = res.status
    throw err
  }
  return body
}

// ---------- fixture mode: a tiny in-memory stand-in for the backend ----------
// Mimics the contract's Step 0 behaviour: hazards grow a little on each poll and
// /route is a straight line to the nearest open shelter.

const GROWTH_PER_TICK = 0.04
const MAX_SCALE = 3.5
const FAKE_SPEED_KMH = 40

let fakeSimTime = hazardsFixture.sim_time
let nextReportId = 1
const fakeHazards = hazardsFixture.features.map((f) => ({
  feature: f,
  center: ringCentroid(f.geometry.coordinates[0]),
  ticks: 0,
}))

function grownFeature(h) {
  const scale = Math.min(1 + GROWTH_PER_TICK * h.ticks, MAX_SCALE)
  const [cx, cy] = h.center
  const ring = h.feature.geometry.coordinates[0].map(([x, y]) => [cx + (x - cx) * scale, cy + (y - cy) * scale])
  return { ...h.feature, geometry: { type: 'Polygon', coordinates: [ring] } }
}

function fakeRoute(lat, lon) {
  const here = [lon, lat]
  const open = sheltersFixture.features.filter((f) => f.properties.open)
  if (open.length === 0) {
    const err = new Error('No reachable shelter from this location')
    err.code = 'no_route'
    err.status = 404
    throw err
  }
  const nearest = open
    .map((f) => ({ f, km: distanceKm(here, f.geometry.coordinates) }))
    .sort((a, b) => a.km - b.km)[0]
  return {
    shelter_id: nearest.f.id,
    shelter_name: nearest.f.properties.name,
    distance_km: Math.round(nearest.km * 10) / 10,
    eta_min: Math.max(1, Math.round((nearest.km / FAKE_SPEED_KMH) * 60)),
    rerouted: false,
    reroute_reason: null,
    steps: [],
    geometry: { type: 'LineString', coordinates: [here, nearest.f.geometry.coordinates] },
  }
}

// ---------- public API ----------

export async function getRoute(lat, lon) {
  if (!USE_FIXTURES) return request(`/route?lat=${lat}&lon=${lon}`)
  return fakeRoute(lat, lon)
}

// Fixture stand-in for the predicted spread the backend adds to /hazards
// (`predicted_min` features): the current shape, larger and drifted east.
const PREDICTED_STEPS = [
  { minutes: 30, scale: 1.5, eastKm: 1.2 },
  { minutes: 60, scale: 2.1, eastKm: 2.6 },
]
function predictedFeatures(grown, center) {
  const [cx, cy] = center
  const kmPerDegLon = 111.32 * Math.cos((cy * Math.PI) / 180)
  return PREDICTED_STEPS.map(({ minutes, scale, eastKm }) => {
    const dx = eastKm / kmPerDegLon
    const ring = grown.geometry.coordinates[0].map(([x, y]) => [cx + dx + (x - cx) * scale, cy + (y - cy) * scale])
    return {
      ...grown,
      id: `${grown.id}_p${minutes}`,
      properties: { ...grown.properties, predicted_min: minutes },
      geometry: { type: 'Polygon', coordinates: [ring] },
    }
  })
}

export async function getHazards() {
  if (!USE_FIXTURES) return request('/hazards')
  fakeSimTime += 1
  fakeHazards.forEach((h) => (h.ticks += 1))
  const features = fakeHazards.flatMap((h) => {
    const grown = grownFeature(h)
    return grown.properties.zone === 'core' ? [...predictedFeatures(grown, h.center), grown] : [grown]
  })
  return { type: 'FeatureCollection', sim_time: fakeSimTime, features }
}

export async function getShelters() {
  if (!USE_FIXTURES) return request('/shelters')
  return structuredClone(sheltersFixture)
}

// Government notifications: [{ id, title, message, severity: advisory|alert|evacuation, time }].
// Not in contract v1 yet (asked for GET /notifications), so a missing endpoint
// just means "no notifications" rather than an error.
export async function getNotifications() {
  if (USE_FIXTURES) return structuredClone(notificationsFixture.notifications)
  try {
    const body = await request('/notifications')
    return Array.isArray(body) ? body : (body?.notifications ?? [])
  } catch (err) {
    if (err.status === 404) return []
    throw err
  }
}

// kind: fire | flooded_road | blocked_road | safe | sos
export async function postReport({ kind, lat, lon, note }) {
  const body = { kind, lat, lon, ...(note ? { note } : {}) }
  if (!USE_FIXTURES) return request('/reports', { method: 'POST', body: JSON.stringify(body) })
  return { id: `rp_${nextReportId++}`, received: true }
}
