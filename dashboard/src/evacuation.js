// Evacuation zones and unsafe shelters, computed client-side from the fire shapes.
// Keep in step with phone/src/evacuation.js (same rule on both surfaces).
//
// - Evacuation zone: a circle around each wildfire as it is now (never the
//   predicted path), centred on the fire, reaching EVAC_BUFFER_M past its farthest
//   edge, so it always covers the whole fire and grows only as the fire grows. It is
//   built from whatever fire shape is drawn, so it follows the history slider.
// - Unsafe shelter: inside the evacuation circle of the fire now or of any forecast
//   outline (GET /forecast, up to +120 min), i.e. the fire is there or will come
//   close enough to put the shelter inside an evacuation zone.

export const EVAC_BUFFER_M = 1000
export const UNSAFE_SHELTER_TEXT = 'Unsafe: Find another shelter'

const M_PER_DEG_LAT = 111320
const CIRCLE_STEPS = 64

function centroid(ring) {
  const pts = ring.length > 1 ? ring.slice(0, -1) : ring
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length]
}

// A circle (closed ring, metres-true) centred on the ring's centre, with radius =
// its farthest vertex + `margin` metres.
export function evacCircle(ring, margin = EVAC_BUFFER_M) {
  const [cx, cy] = centroid(ring)
  const mPerDegLon = M_PER_DEG_LAT * Math.cos((cy * Math.PI) / 180)
  const reach = Math.max(0, ...ring.map(([x, y]) => Math.hypot((x - cx) * mPerDegLon, (y - cy) * M_PER_DEG_LAT)))
  const r = reach + margin
  const circle = Array.from({ length: CIRCLE_STEPS }, (_, i) => {
    const a = (i / CIRCLE_STEPS) * 2 * Math.PI
    return [cx + (r * Math.sin(a)) / mPerDegLon, cy + (r * Math.cos(a)) / M_PER_DEG_LAT]
  })
  return [...circle, circle[0]]
}

function pointInRing([x, y], ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

const isFireNow = (f) =>
  f.properties?.kind === 'wildfire' &&
  f.properties?.zone === 'core' &&
  f.properties?.predicted_min == null &&
  f.geometry?.type === 'Polygon'

// One evacuation circle per wildfire drawn on the map (current fire only).
export function evacZones(hazards) {
  const features = (hazards?.features ?? []).filter(isFireNow).map((f) => ({
    type: 'Feature',
    id: `${f.id}:evac`,
    properties: { fire_id: f.id },
    geometry: { type: 'Polygon', coordinates: [evacCircle(f.geometry.coordinates[0])] },
  }))
  return { type: 'FeatureCollection', features }
}

// Circles that count for shelter safety: around the fire now and every forecast outline.
export function dangerRings(hazards, forecastOutlines = []) {
  return [
    ...(hazards?.features ?? []).filter(isFireNow),
    ...forecastOutlines.filter((o) => o.geometry?.type === 'Polygon'),
  ].map((f) => evacCircle(f.geometry.coordinates[0]))
}

// Ids of shelters inside any danger circle.
export function unsafeShelterIds(shelters, rings) {
  const ids = new Set()
  for (const s of shelters?.features ?? []) {
    if (rings.some((ring) => pointInRing(s.geometry.coordinates, ring))) ids.add(s.id)
  }
  return ids
}
