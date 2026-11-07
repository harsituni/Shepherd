import { API_URL, USE_FIXTURES } from './config.js'
import { distanceKm, pointInRing, ringCentroid } from './geo.js'
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
// Hazards grow a little on each poll; /route returns contract v2 options as
// straight lines to the nearest open shelters.

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

// Fixture fire forecast: minutes for the fire to spread one km, the contract's
// 30-minute road-closing buffer and 120-minute forecast horizon, and the backend's
// "no threat" margin sentinel (backend/routing/router.py).
const FAKE_FIRE_MIN_PER_KM = 12
const BUFFER_MIN = 30
const HORIZON_MIN = 120
const NO_THREAT = 999
const SAMPLES = 8
let fakeForecast = { key: null, arrivals: null }

// Sim minute the fake fire reaches a point, or null beyond the forecast horizon.
function fakeArrival(point, at) {
  let best = Infinity
  for (const h of fakeHazards) {
    const ring = grownFeature(h).geometry.coordinates[0]
    const km = pointInRing(point, ring) ? 0 : Math.min(...ring.map((p) => distanceKm(point, p)))
    best = Math.min(best, at + km * FAKE_FIRE_MIN_PER_KM)
  }
  return best - at > HORIZON_MIN ? null : Math.round(best)
}

// One v2 option, scored like the backend: a sample is blocked if you'd reach it
// later than BUFFER_MIN before the fire does.
function fakeOption(id, here, shelter, arrivals) {
  const km = distanceKm(here, shelter.geometry.coordinates)
  const eta = Math.max(1, Math.round((km / FAKE_SPEED_KMH) * 60))
  let margin = NO_THREAT
  let clearUntil = null
  let reason = null
  arrivals.forEach((arrival, i) => {
    if (arrival == null) return
    const reach = fakeSimTime + (eta * i) / (SAMPLES - 1)
    const spare = Math.floor(arrival - BUFFER_MIN - reach)
    clearUntil = clearUntil == null ? arrival - BUFFER_MIN : Math.min(clearUntil, arrival - BUFFER_MIN)
    if (spare < margin) margin = spare
    if (spare < 0 && !reason) {
      reason = `Roads on this route close at T+${arrival - BUFFER_MIN}, ${BUFFER_MIN} min before the fire arrives. You'd reach them at T+${Math.round(reach)}.`
    }
  })
  const status = margin >= 60 ? 'ok' : margin >= 0 ? 'tight' : 'blocked'
  const usable = status !== 'blocked'
  return {
    id,
    shelter_id: shelter.id,
    shelter_name: shelter.properties.name,
    distance_km: Math.round(km * 10) / 10,
    eta_min: eta,
    margin_min: margin,
    status,
    clear_until_sim_min: usable ? clearUntil : null,
    clear_until_label: usable && clearUntil != null ? `Clear until T+${clearUntil}` : null,
    reason: usable ? null : reason,
    geometry: { type: 'LineString', coordinates: [here, shelter.geometry.coordinates] },
  }
}

// Fixture /route in the contract v2 shape: up to 3 nearest open shelters, each
// ok / tight / blocked against the fake fire. The forecast is snapshotted per
// location (like a real forecast it only changes when conditions do), so margins
// shrink as sim time passes and a route can turn tight, then blocked.
function fakeRoute(lat, lon) {
  const here = [lon, lat]
  const open = sheltersFixture.features
    .filter((f) => f.properties.open)
    .map((f) => ({ f, km: distanceKm(here, f.geometry.coordinates) }))
    .sort((a, b) => a.km - b.km)
    .slice(0, 3)
  const noRoute = (message) => Object.assign(new Error(message), { code: 'no_route', status: 404 })
  if (open.length === 0) throw noRoute('No reachable shelter from this location')

  const key = `${lat.toFixed(4)},${lon.toFixed(4)}`
  if (fakeForecast.key !== key) {
    const arrivals = open.map(({ f }) => {
      const [x1, y1] = here
      const [x2, y2] = f.geometry.coordinates
      return Array.from({ length: SAMPLES }, (_, i) => {
        const t = i / (SAMPLES - 1)
        return fakeArrival([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], fakeSimTime)
      })
    })
    fakeForecast = { key, arrivals }
  }

  const options = open.map(({ f }, i) => fakeOption(`rt_${i + 1}`, here, f, fakeForecast.arrivals[i]))
  const usable = options.filter((o) => o.status !== 'blocked')
  if (usable.length === 0) throw noRoute('No usable evacuation route under the current fire forecast')
  const best = usable.reduce((a, b) => (b.margin_min > a.margin_min || (b.margin_min === a.margin_min && b.eta_min < a.eta_min) ? b : a))
  const leaveBy = best.margin_min === NO_THREAT ? null : fakeSimTime + best.margin_min
  return {
    lat,
    lon,
    sim_time: fakeSimTime,
    leave_by_sim_min: leaveBy,
    leave_by_label: leaveBy == null ? null : `Leave within ${best.margin_min} min (sim)`,
    best_route_id: best.id,
    options,
    excluded: options.filter((o) => o.status === 'blocked').map((o) => ({ shelter_id: o.shelter_id, reason: o.reason })),
  }
}

// /route comes back as contract v2 (`options` + `leave_by_*`) or, until the backend
// migrates, the Step 0 flat shape. Flatten v2's best option onto the top level so the
// map and route details read one shape; `leave_by_sim_min` is undefined for v1.
export function normalizeRoute(body) {
  if (!Array.isArray(body?.options)) return body
  const best = body.options.find((o) => o.id === body.best_route_id) ?? body.options.find((o) => o.status !== 'blocked')
  return {
    rerouted: false,
    reroute_reason: null,
    steps: [],
    ...body,
    ...(best ?? {}),
    id: undefined,
    route_id: best?.id ?? null,
  }
}

// The route to show: the option the user picked (by shelter, since option ids can be
// renumbered between polls) or the backend's best. If their pick has since become
// blocked, fall back to the best and return it as `lost` so the UI can say why.
export function withChoice(route, shelterId) {
  const picked = shelterId ? route?.options?.find((o) => o.shelter_id === shelterId) : null
  if (!picked) return { shown: route, lost: null }
  if (picked.status === 'blocked') return { shown: route, lost: picked }
  return { shown: { ...route, ...picked, id: undefined, route_id: picked.id }, lost: null }
}

// ---------- public API ----------

export async function getRoute(lat, lon) {
  if (!USE_FIXTURES) return normalizeRoute(await request(`/route?lat=${lat}&lon=${lon}`))
  return normalizeRoute(fakeRoute(lat, lon))
}

// Sim clock: { state: idle|running|paused, sim_time, speed, ... }. Null if the
// backend doesn't have /sim/state, so the phone still works against older builds.
export async function getSimState() {
  if (USE_FIXTURES) return { state: 'running', scenario: 'wildfire', sim_time: fakeSimTime, speed: 1 }
  try {
    return await request('/sim/state')
  } catch (err) {
    if (err.status === 404) return null
    throw err
  }
}

// The predicted path comes from GET /forecast (contract v2): outlines at t_min =
// 15, 30 … 120 minutes from now. The map draws the 30 and 60 min ones as
// `predicted_min` features, like the dashboard; all eight would crowd a phone map.
const FORECAST_MIN_SHOWN = [30, 60]
async function getForecastFeatures() {
  const { outlines = [] } = await request('/forecast')
  return outlines
    .filter((o) => FORECAST_MIN_SHOWN.includes(o.t_min) && o.geometry)
    .map((o) => ({ type: 'Feature', id: o.id, properties: { ...o.properties, predicted_min: o.t_min }, geometry: o.geometry }))
}

// Fixture stand-in for the predicted spread (`predicted_min` features): the
// current shape, larger and drifted east.
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

// The hazard now (/hazards) plus the predicted path (/forecast). If the forecast
// fails, the hazard still draws, just without predicted rings.
export async function getHazards() {
  if (!USE_FIXTURES) {
    const [hazards, predicted] = await Promise.all([request('/hazards'), getForecastFeatures().catch(() => [])])
    return { ...hazards, features: [...predicted, ...(hazards.features ?? [])] }
  }
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

// Evacuee heartbeat (contract v2): { id, lat, lon, route_id, route_status, shelter_id },
// upserted by id. Sent every ~2 s while evacuating so the dashboard can show the dot.
export async function postEvacuee(body) {
  if (!USE_FIXTURES) return request('/evacuees', { method: 'POST', body: JSON.stringify(body) })
  return { id: body.id, received: true }
}

// kind: fire | flooded_road | blocked_road | safe | sos | other (other: not in contract v1 yet)
export async function postReport({ kind, lat, lon, note }) {
  const body = { kind, lat, lon, ...(note ? { note } : {}) }
  if (!USE_FIXTURES) return request('/reports', { method: 'POST', body: JSON.stringify(body) })
  return { id: `rp_${nextReportId++}`, received: true }
}
