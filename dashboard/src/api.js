import { API_URL, USE_FIXTURES } from './config.js'
import hazardsFixture from '../../shared/fixtures/hazards.json'
import sheltersFixture from '../../shared/fixtures/shelters.json'
import reportsFixture from '../../shared/fixtures/reports.json'

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

// ---------- fixture mode: a tiny in-memory stand-in for the backend ----------
// Mimics the contract's Step 0 behaviour: every hazard grows a little on each poll,
// and POST /hazards adds a circle.

const GROWTH_PER_TICK = 0.04 // +4% size per poll
const MAX_SCALE = 3.5

let fakeSimTime = hazardsFixture.sim_time
let nextHazardId = hazardsFixture.features.length + 1
const fakeHazards = hazardsFixture.features.map((f) => track(structuredClone(f)))

function track(feature) {
  const ring = feature.geometry.coordinates[0]
  const pts = ring.slice(0, -1) // drop the closing point
  const center = [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ]
  return { feature, center, baseRing: ring, ticks: 0 }
}

function grownFeature(h) {
  const scale = Math.min(1 + GROWTH_PER_TICK * h.ticks, MAX_SCALE)
  const [cx, cy] = h.center
  const ring = h.baseRing.map(([x, y]) => [cx + (x - cx) * scale, cy + (y - cy) * scale])
  return { ...h.feature, geometry: { type: 'Polygon', coordinates: [ring] } }
}

function circlePolygon(lon, lat, radiusM, steps = 32) {
  const dLat = radiusM / 111320
  const dLon = radiusM / (111320 * Math.cos((lat * Math.PI) / 180))
  const ring = []
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * 2 * Math.PI
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)])
  }
  ring.push(ring[0]) // closed polygon
  return { type: 'Polygon', coordinates: [ring] }
}

// ---------- public API ----------

export async function getHazards() {
  if (!USE_FIXTURES) return request('/hazards')
  fakeSimTime += 1
  fakeHazards.forEach((h) => (h.ticks += 1))
  return {
    type: 'FeatureCollection',
    sim_time: fakeSimTime,
    features: fakeHazards.map(grownFeature),
  }
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
  if (!USE_FIXTURES) {
    return request('/hazards', {
      method: 'POST',
      body: JSON.stringify({ kind, lat, lon, radius_m }),
    })
  }
  const feature = {
    type: 'Feature',
    id: `hz_${nextHazardId++}`,
    properties: { kind, zone: 'core', source: 'sim' },
    geometry: circlePolygon(lon, lat, radius_m),
  }
  fakeHazards.push(track(feature))
  return feature
}
