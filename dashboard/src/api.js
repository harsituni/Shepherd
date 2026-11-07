import { API_URL, USE_FIXTURES } from './config.js'
import hazardsFixture from '../../shared/fixtures/hazards.json'
import sheltersFixture from '../../shared/fixtures/shelters.json'
import reportsFixture from '../../shared/fixtures/reports.json'

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

function fakeState() {
  advanceFake()
  return {
    state: fake.state,
    scenario: fake.scenario,
    sim_time: fake.state === 'idle' ? null : Math.floor(fake.minutes),
    speed: fake.speed,
  }
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
    // Tornado: a compact damage circle that travels downwind and widens slowly.
    const travel = (p.wind_kmh * 1000 * 0.6 * minutes) / 60 // metres moved
    const centre = offset(origin, travel * Math.sin(toward), travel * Math.cos(toward))
    const r = 200 + 2 * minutes
    return ring(
      Array.from({ length: steps }, (_, i) => {
        const a = (i / steps) * 2 * Math.PI
        return offset(centre, r * Math.cos(a), r * Math.sin(a))
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
  const feature = (id, props, minutes) => ({
    type: 'Feature',
    id,
    properties: { kind, source: 'sim', ...props },
    geometry: fakeShape(minutes),
  })
  return [feature('hz_sim_buffer', { zone: 'buffer' }, t + 10), feature('hz_sim_core', { zone: 'core' }, t)]
}

// Same shape as GET /forecast: outlines at 15, 30 … 120 minutes from now.
function fakeForecast() {
  const { sim_time } = fakeState()
  const outlines =
    fake.state === 'idle' || fake.scenario !== 'wildfire'
      ? []
      : Array.from({ length: 8 }, (_, i) => {
          const t_min = (i + 1) * 15
          return {
            t_min,
            type: 'Feature',
            id: `fc_${t_min}`,
            properties: { kind: 'wildfire', t_min, zone: 'predicted' },
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

export async function getShelters() {
  if (!USE_FIXTURES) return request('/shelters')
  return structuredClone(sheltersFixture)
}

export async function getReports() {
  if (!USE_FIXTURES) return request('/reports')
  return structuredClone(reportsFixture)
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
