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
// Hazards grow a little on each poll; /route returns v3 options (shared/route_v3.md)
// as straight lines to the nearest open shelters.

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
// 30-minute road-closing buffer and 120-minute forecast horizon.
const FAKE_FIRE_MIN_PER_KM = 12
const BUFFER_MIN = 30
const HORIZON_MIN = 120
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

// One v3 option, scored like the backend: a sample is blocked if you'd reach it
// later than BUFFER_MIN before the fire does. margin null = no threat.
function fakeOption(here, shelter, arrivals) {
  const km = distanceKm(here, shelter.geometry.coordinates)
  const eta = Math.max(1, Math.round((km / FAKE_SPEED_KMH) * 60))
  let margin = null
  let clearUntil = null
  let reason = null
  arrivals.forEach((arrival, i) => {
    if (arrival == null) return
    const reach = fakeSimTime + (eta * i) / (SAMPLES - 1)
    const spare = Math.floor(arrival - BUFFER_MIN - reach)
    clearUntil = clearUntil == null ? arrival - BUFFER_MIN : Math.min(clearUntil, arrival - BUFFER_MIN)
    if (margin == null || spare < margin) margin = spare
    if (spare < 0 && !reason) {
      reason = `Roads on this route close at T+${arrival - BUFFER_MIN}, ${BUFFER_MIN} min before the fire arrives. You'd reach them at T+${Math.round(reach)}.`
    }
  })
  const status = margin == null || margin >= 60 ? 'ok' : margin >= 0 ? 'tight' : 'blocked'
  const usable = status !== 'blocked'
  return {
    id: `rt_${shelter.id}_fastest`,
    role: 'fastest',
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

// Fixture /route in the v3 shape: up to 3 nearest open shelters, each
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

  const spare = (o) => (o.margin_min == null ? Infinity : o.margin_min)
  const rank = { ok: 0, tight: 1, blocked: 2 }
  const options = open
    .map(({ f }, i) => fakeOption(here, f, fakeForecast.arrivals[i]))
    .sort((a, b) => rank[a.status] - rank[b.status] || (a.status === 'ok' ? a.eta_min - b.eta_min : spare(b) - spare(a)))
  const best = options[0].status === 'blocked' ? null : options[0]
  const leaveBy = best?.margin_min == null ? null : fakeSimTime + best.margin_min
  return {
    lat,
    lon,
    sim_time: fakeSimTime,
    route_status: best ? 'viable' : 'blocked',
    best_route_id: best?.id ?? null,
    no_safe_route: !best,
    leave_by_sim_min: leaveBy,
    leave_by_label: leaveBy == null ? null : `Leave within ${best.margin_min} min (sim)`,
    options,
    excluded: [],
  }
}

// /route comes back as v3 (`route_status`, shared/route_v3.md), contract v2 or the
// Step 0 flat shape. Flatten the best option onto the top level so the map and route
// details read one shape. v3 can have no best (nothing safe, or nothing confirmed):
// then nothing is flattened and there is no route line, only greyed options.
const roundKm = (km) => (km == null || Number.isNaN(Number(km)) ? km : Math.round(Number(km) * 10) / 10)

export function normalizeRoute(body) {
  if (!Array.isArray(body?.options)) {
    if (body?.distance_km == null) return body
    return { ...body, distance_km: roundKm(body.distance_km) }
  }
  const options = body.options.map((o) => ({ ...o, distance_km: roundKm(o.distance_km) }))
  const v3 = body.route_status != null
  const best =
    options.find((o) => o.id === body.best_route_id) ?? (v3 ? undefined : options.find((o) => o.status !== 'blocked'))
  return {
    rerouted: false,
    reroute_reason: null,
    steps: [],
    ...body,
    options,
    ...(best ?? {}),
    distance_km: best ? roundKm(best.distance_km) : undefined,
    id: undefined,
    route_id: best?.id ?? null,
  }
}

// Only these can be picked, recommended or driven; blocked and indeterminate
// routes are shown greyed.
export const usable = (o) => o?.status === 'ok' || o?.status === 'tight'

// The route to show: the option the user picked (by its stable id; the backend keeps
// it in `options` because the phone sends check_route_id) or the backend's best. If
// their pick is no longer usable, fall back to the best and return it as `lost`.
export function withChoice(route, routeId) {
  const picked = routeId ? route?.options?.find((o) => o.id === routeId) : null
  if (!picked) return { shown: route, lost: null }
  if (!usable(picked)) return { shown: route, lost: picked }
  return { shown: { ...route, ...picked, id: undefined, route_id: picked.id }, lost: null }
}

// ---------- public API ----------

// checkRouteId: the id of the route the person picked, so it stays in the answer.
export async function getRoute(lat, lon, checkRouteId = null) {
  const check = checkRouteId ? `&check_route_id=${encodeURIComponent(checkRouteId)}` : ''
  if (!USE_FIXTURES) return normalizeRoute(await request(`/route?lat=${lat}&lon=${lon}${check}`))
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
// 15, 30 … 120 minutes from now. The map draws only the 60 min one as a
// `predicted_min` feature, like the dashboard: two nested dotted rings read as a
// doubled border.
const FORECAST_MIN_SHOWN = [60]
const toPredicted = (o) => ({ type: 'Feature', id: o.id, properties: { ...o.properties, predicted_min: o.t_min }, geometry: o.geometry })

// Fixture stand-in for the predicted spread (`predicted_min` features): the
// current shape, larger and drifted east.
const PREDICTED_STEPS = [{ minutes: 60, scale: 2.1, eastKm: 2.6 }]
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

// The hazard now (/hazards) plus the predicted path (/forecast). All forecast
// outlines also ride along as `forecast` (not GeoJSON) for the unsafe-shelter
// check. If the forecast fails, the hazard still draws, just without predictions.
export async function getHazards() {
  if (!USE_FIXTURES) {
    const [hazards, fc] = await Promise.all([request('/hazards'), request('/forecast').catch(() => null)])
    const outlines = (fc?.outlines ?? []).filter((o) => o.geometry)
    const predicted = outlines.filter((o) => FORECAST_MIN_SHOWN.includes(o.t_min)).map(toPredicted)
    return { ...hazards, features: [...predicted, ...(hazards.features ?? [])], forecast: outlines }
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

// Priority residents (not in the contract yet): { id, id_type, id_last4, needs, note? }.
// Only the last 4 characters of the ID ever leave the phone.
export async function postPriority(body) {
  if (!USE_FIXTURES) return request('/priority', { method: 'POST', body: JSON.stringify(body) })
  return { id: body.id, priority: true }
}

export async function deletePriority(id) {
  if (!USE_FIXTURES) return request(`/priority/${encodeURIComponent(id)}`, { method: 'DELETE' })
  return { id, priority: false }
}

// kind: fire | flooded_road | blocked_road | safe | sos | other (other: not in contract v1 yet)
export async function postReport({ kind, lat, lon, note }) {
  const body = { kind, lat, lon, ...(note ? { note } : {}) }
  if (!USE_FIXTURES) return request('/reports', { method: 'POST', body: JSON.stringify(body) })
  return { id: `rp_${nextReportId++}`, received: true }
}
