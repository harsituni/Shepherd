import { API_URL, USE_FIXTURES } from './config.js'
import hazardsFixture from '../../shared/fixtures/hazards.json'
import sheltersFixture from '../../shared/fixtures/shelters.json'
import reportsFixture from '../../shared/fixtures/reports.json'
import evacueesFixture from '../../shared/fixtures/evacuees.json'

// The disaster simulation runs on the backend (shared/contract.md "Simulation
// control"). The dashboard only sends the scenario + conditions and draws what
// /hazards and /forecast return. History for the timeline slider is recorded
// client-side (src/history.js); the backend keeps none.

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
    throw err
  }
  return body
}

const post = (path, body) =>
  request(path, { method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) })

// ---------- fixture mode: a tiny in-memory stand-in for the backend ----------
// NOT the hazard model. It only returns contract-shaped data so the dashboard can
// be built and demoed before /sim/* exists: a shape that grows over sim time
// (pushed downwind for fire) plus the same shape at T+30 / T+60 as the "prediction".

const SIM_MIN_PER_SECOND = 1 // at 1×, one sim minute per real second

let sampleHazards = structuredClone(hazardsFixture.features) // shown until a simulation starts
let nextHazardId = hazardsFixture.features.length + 1
const fake = { state: 'idle', scenario: null, params: null, minutes: 0, speed: 1, lastTs: 0 }

function advanceFake() {
  const now = Date.now()
  if (fake.state === 'running') fake.minutes += ((now - fake.lastTs) / 1000) * SIM_MIN_PER_SECOND * fake.speed
  fake.lastTs = now
}

const EF_FAKE = [
  { wind_kmh: 121, wind_mph: 75, peak_m: 45 },
  { wind_kmh: 158, wind_mph: 98, peak_m: 80 },
  { wind_kmh: 198, wind_mph: 123, peak_m: 130 },
  { wind_kmh: 241, wind_mph: 150, peak_m: 190 },
  { wind_kmh: 295, wind_mph: 183, peak_m: 260 },
  { wind_kmh: 354, wind_mph: 220, peak_m: 340 },
]

function fakeTornadoStats(minutes, params) {
  const peak = Math.max(0, Math.min(5, params?.ef_rating ?? 3))
  const inten =
    minutes < 8 ? 0.15 + (minutes / 8) * 0.55 : minutes < 35 ? 0.85 : Math.max(0.08, 1 - ((minutes - 35) / 35) * 0.92)
  const ef = Math.max(0, Math.min(peak, Math.round(peak * inten)))
  const band = EF_FAKE[ef]
  const phase = minutes <= 8 ? 'organizing' : minutes <= 35 ? 'mature' : minutes <= 70 ? 'dissipating' : 'remnant'
  const kmh = Math.min(85, Math.max(32, (params?.wind_kmh ?? 40) * 0.65))
  return {
    ef_rating: ef,
    ef_label: `EF${ef}`,
    ef_peak: peak,
    ef_peak_label: `EF${peak}`,
    ef_desc: ['Light damage', 'Moderate damage', 'Considerable damage', 'Severe damage', 'Devastating damage', 'Incredible damage'][ef],
    phase,
    intensity: Math.round(inten * 100) / 100,
    wind_est_mph: band.wind_mph,
    wind_est_kmh: band.wind_kmh,
    path_width_m: Math.round((40 + band.peak_m * inten) * 2),
    forward_speed_kmh: Math.round(kmh * 10) / 10,
    track_km: Math.round(((kmh * 1000 * minutes) / 60 / 1000) * 10) / 10,
    heading_deg: ((params?.wind_from_deg ?? 270) + 180) % 360,
  }
}

function fakeState() {
  advanceFake()
  const body = {
    state: fake.state,
    scenario: fake.scenario,
    sim_time: fake.state === 'idle' ? null : Math.floor(fake.minutes),
    speed: fake.speed,
    wind_kmh: fake.params?.wind_kmh,
    wind_from_deg: fake.params?.wind_from_deg,
  }
  if (fake.state !== 'idle' && fake.scenario === 'tornado') {
    body.tornado = fakeTornadoStats(fake.minutes, fake.params)
  }
  return body
}

// Offset a point by metres east/north.
function offset([lon, lat], eastM, northM) {
  return [lon + eastM / (111320 * Math.cos((lat * Math.PI) / 180)), lat + northM / 111320]
}

function ring(points) {
  return { type: 'Polygon', coordinates: [[...points, points[0]]] }
}

function fakeShape(minutes) {
  const p = fake.params
  const origin = [p.lon, p.lat]
  const steps = 48
  const toward = ((p.wind_from_deg + 180) * Math.PI) / 180 // compass bearing it blows toward
  if (fake.scenario === 'tornado') {
    // Fixture stand-in for TornadoSim: storm-speed track, right-flank offset, slight curve.
    const kmh = Math.min(85, Math.max(32, p.wind_kmh * 0.65))
    const travel = (kmh * 1000 * minutes) / 60
    const right = toward + Math.PI / 2
    const curve = (travel / 1000) * 55
    const sine = 380 * Math.sin(travel * ((2 * Math.PI) / 6500))
    const centre = offset(
      origin,
      travel * Math.sin(toward) + 900 * Math.sin(right) - 600 * Math.sin(toward) + (curve + sine) * Math.sin(right),
      travel * Math.cos(toward) + 900 * Math.cos(right) - 600 * Math.cos(toward) + (curve + sine) * Math.cos(right),
    )
    const peak = Math.max(0, Math.min(5, p.ef_rating ?? 3))
    const inten = minutes < 8 ? 0.2 + (minutes / 8) * 0.5 : minutes < 35 ? 0.85 : Math.max(0.1, 1 - (minutes - 35) / 40)
    const r = 40 + EF_FAKE[peak].peak_m * inten
    const along = r * 1.25
    const across = r * 0.85
    const ca = Math.cos(toward)
    const sa = Math.sin(toward)
    return ring(
      Array.from({ length: steps }, (_, i) => {
        const a = (i / steps) * 2 * Math.PI
        const x = along * Math.cos(a)
        const y = across * Math.sin(a)
        return offset(centre, x * sa + y * ca, x * ca - y * sa)
      }),
    )
  }
  // Wildfire: an ellipse stretched downwind; faster with wind and dry fuel, slower when humid.
  const fuel = p.fuel_dryness ?? 0.7 // the UI no longer sends it; contract default
  const rate = (2 + 0.9 * p.wind_kmh) * (0.3 + 1.2 * fuel) * (1.4 - p.humidity_pct / 100) // m/min
  const head = 120 + rate * minutes
  const back = 120 + (rate * minutes) / (1 + p.wind_kmh / 10)
  const half = (head + back) / (2 * (1 + p.wind_kmh / 40))
  const shift = (head - back) / 2
  return ring(
    Array.from({ length: steps }, (_, i) => {
      const a = (i / steps) * 2 * Math.PI
      const along = shift + ((head + back) / 2) * Math.cos(a)
      const across = half * Math.sin(a)
      const east = along * Math.sin(toward) + across * Math.cos(toward)
      const north = along * Math.cos(toward) - across * Math.sin(toward)
      return offset(origin, east, north)
    }),
  )
}

function fakeHazards() {
  if (fake.state === 'idle') return sampleHazards
  const kind = fake.scenario
  const t = fake.minutes
  const tornado = kind === 'tornado' ? fakeTornadoStats(t, fake.params) : null
  const feature = (id, props, minutes) => ({
    type: 'Feature',
    id,
    properties: { kind, source: 'sim', ...props },
    geometry: fakeShape(minutes),
  })
  if (tornado) {
    return [
      feature('hz_sim_buffer', { zone: 'buffer', role: 'debris', ef_rating: tornado.ef_rating }, t + 10),
      feature('hz_sim_core', { zone: 'core', ...tornado }, t),
    ]
  }
  return [feature('hz_sim_buffer', { zone: 'buffer' }, t + 10), feature('hz_sim_core', { zone: 'core' }, t)]
}

// Same shape as GET /forecast: outlines at 15, 30 … 120 minutes from now.
function fakeForecast() {
  const { sim_time } = fakeState()
  const outlines =
    fake.state === 'idle' || (fake.scenario !== 'wildfire' && fake.scenario !== 'tornado')
      ? []
      : Array.from({ length: 8 }, (_, i) => {
          const t_min = (i + 1) * 15
          return {
            t_min,
            type: 'Feature',
            id: `fc_${t_min}`,
            properties: { kind: fake.scenario, t_min, zone: 'predicted' },
            geometry: fakeShape(fake.minutes + t_min),
          }
        })
  return { sim_time: sim_time ?? 0, horizon_min: 120, outlines }
}

// ---------- public API ----------

// The hazard as it is now. The predicted path comes from getForecast().
export async function getHazards() {
  if (!USE_FIXTURES) return request('/hazards')
  const { sim_time } = fakeState()
  return {
    type: 'FeatureCollection',
    sim_time: sim_time ?? hazardsFixture.sim_time,
    features: fakeHazards(),
  }
}

// GET /forecast (contract v2): { sim_time, horizon_min, outlines: [Feature with t_min] },
// t_min = 15, 30 … 120 minutes from now; outlines is [] when idle.
export async function getForecast() {
  if (!USE_FIXTURES) return request('/forecast')
  return fakeForecast()
}

// GET /evacuees (contract v2): Points, one per phone that has set a location,
// with route_id / route_status / shelter_id / updated_sim_time. Dropped by the
// backend after 30 s without a heartbeat.
export async function getEvacuees() {
  if (!USE_FIXTURES) return request('/evacuees')
  return structuredClone(evacueesFixture)
}

// GET /roads/closed (contract v2.1): OSM edges past the fire close deadline.
export async function getClosedRoads() {
  if (!USE_FIXTURES) return request('/roads/closed')
  return { type: 'FeatureCollection', sim_time: 0, count: 0, features: [] }
}

export async function getShelters() {
  if (!USE_FIXTURES) return request('/shelters')
  return structuredClone(sheltersFixture)
}

export async function getReports() {
  if (!USE_FIXTURES) return request('/reports')
  return structuredClone(reportsFixture)
}

// Government updates (Notify tab). POST stores one; phones poll GET /notifications.
// Not in contract v1 yet; fixture mode keeps them in memory for this page load.
const sentFixture = []

export async function getNotifications() {
  if (USE_FIXTURES) return structuredClone(sentFixture)
  const body = await request('/notifications')
  return Array.isArray(body) ? body : (body?.notifications ?? [])
}

export async function postNotification({ title, message, severity, target }) {
  if (!USE_FIXTURES) return post('/notifications', { title, message, severity, target })
  const note = {
    id: `nt_${sentFixture.length + 1}`,
    title,
    message,
    severity,
    target,
    time: new Date().toISOString(),
  }
  sentFixture.unshift(note)
  return structuredClone(note)
}

export async function postHazard({ kind, lat, lon, radius_m }) {
  if (!USE_FIXTURES) return post('/hazards', { kind, lat, lon, radius_m })
  const feature = {
    type: 'Feature',
    id: `hz_${nextHazardId++}`,
    properties: { kind, zone: 'core', source: 'sim' },
    geometry: ring(
      Array.from({ length: 32 }, (_, i) => {
        const a = (i / 32) * 2 * Math.PI
        return offset([lon, lat], radius_m * Math.cos(a), radius_m * Math.sin(a))
      }),
    ),
  }
  sampleHazards.push(feature)
  return feature
}

export async function deleteHazards() {
  if (!USE_FIXTURES) return request('/hazards', { method: 'DELETE' })
  sampleHazards = []
  return { ok: true }
}

// ---------- simulation control (runs on the backend) ----------

export async function getSimState() {
  if (!USE_FIXTURES) return request('/sim/state')
  return fakeState()
}

// Wildfire: { scenario: 'wildfire', lat, lon, wind_kmh, wind_from_deg, humidity_pct }
// Tornado:  { scenario: 'tornado', lat, lon, wind_kmh, wind_from_deg }
// fuel_dryness is left to the backend default. humidity_pct and the tornado scenario
// are not in contract v1 yet (asked for in dashboard/CLAUDE.md).
export async function startSim(body) {
  if (!USE_FIXTURES) return post('/sim/start', body)
  Object.assign(fake, { state: 'running', scenario: body.scenario, params: body, minutes: 0, lastTs: Date.now() })
  return fakeState()
}

export async function pauseSim() {
  if (!USE_FIXTURES) return post('/sim/pause')
  advanceFake()
  if (fake.state === 'running') fake.state = 'paused'
  return fakeState()
}

export async function resumeSim() {
  if (!USE_FIXTURES) return post('/sim/resume')
  advanceFake()
  if (fake.state === 'paused') fake.state = 'running'
  return fakeState()
}

export async function resetSim() {
  if (!USE_FIXTURES) return post('/sim/reset')
  Object.assign(fake, { state: 'idle', scenario: null, params: null, minutes: 0 })
  return fakeState()
}

// Change wind while a simulation is running or paused (contract v2):
// { wind_kmh, wind_from_deg }, both required. Returns the /sim/state shape.
export async function setSimWind(wind_kmh, wind_from_deg) {
  if (!USE_FIXTURES) return post('/sim/wind', { wind_kmh, wind_from_deg })
  advanceFake()
  if (fake.params) fake.params = { ...fake.params, wind_kmh, wind_from_deg }
  return fakeState()
}

export async function setSimSpeed(multiplier) {
  if (!USE_FIXTURES) return post('/sim/speed', { multiplier })
  advanceFake()
  fake.speed = multiplier
  return fakeState()
}

// ---------- traffic (contract v2.1) ----------

// People/cars to evacuate from a pin + local day/time (edmonton zone model).
export async function getEvacProjection({ lat, lon, scenario = 'wildfire', windKmh = 20, when }) {
  if (USE_FIXTURES) {
    return {
      ok: true,
      people: 12000,
      cars: 8000,
      area_label: 'Edmonton suburbs',
      daypart: 'weekday midday',
      label: '~12,000 people / 8,000 cars · Edmonton suburbs · weekday midday',
      method: 'fixture',
    }
  }
  const q = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    scenario,
    wind_kmh: String(windKmh),
  })
  if (when) q.set('when', when)
  return request(`/traffic/projection?${q}`)
}

export async function getTraffic() {
  if (!USE_FIXTURES) return request('/traffic')
  return {
    enabled: false,
    anti_gridlock: true,
    simulated_count: 10000,
    real_count: 0,
    active_count: 0,
    metrics: {},
    compare: null,
    edges: { type: 'FeatureCollection', features: [] },
  }
}

export async function getTrafficState() {
  if (!USE_FIXTURES) return request('/traffic/state')
  return getTraffic()
}

export async function setTrafficConfig(body) {
  if (!USE_FIXTURES) return post('/traffic/config', body)
  return { ...body, metrics: {}, compare: null }
}

export async function compareTraffic() {
  if (!USE_FIXTURES) return post('/traffic/compare')
  return {
    ok: true,
    without_min: 74,
    with_min: 41,
    saved_min: 33,
    label: 'Clearance time 74 → 41 min',
  }
}

export async function rebalanceTraffic() {
  if (!USE_FIXTURES) return post('/traffic/rebalance')
  return { ok: true }
}
