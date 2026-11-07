// Small geometry helpers. Coordinates are always [lon, lat].

const R_KM = 6371

const rad = (d) => (d * Math.PI) / 180

export function distanceKm([lon1, lat1], [lon2, lat2]) {
  const dLat = rad(lat2 - lat1)
  const dLon = rad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R_KM * Math.asin(Math.sqrt(a))
}

// Compass bearing from a to b, 0 = north, clockwise.
export function bearingDeg([lon1, lat1], [lon2, lat2]) {
  const y = Math.sin(rad(lon2 - lon1)) * Math.cos(rad(lat2))
  const x =
    Math.cos(rad(lat1)) * Math.sin(rad(lat2)) - Math.sin(rad(lat1)) * Math.cos(rad(lat2)) * Math.cos(rad(lon2 - lon1))
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

const COMPASS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']
export const compassWord = (deg) => COMPASS[Math.round(deg / 45) % 8]

export function pointInRing([x, y], ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

export function ringCentroid(ring) {
  const pts = ring.length > 1 ? ring.slice(0, -1) : ring
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length]
}

// Predicted-spread features carry `predicted_min` (30, 60); they are not the hazard now.
export const isPredicted = (f) => f.properties?.predicted_min != null
export const isCurrentCore = (f) =>
  !isPredicted(f) && f.properties?.zone === 'core' && f.geometry?.type === 'Polygon'

// Which way a hazard is heading: from its current centroid toward the centroid of the
// nearest-in-time predicted feature of the same kind. Null when there's no prediction
// or it isn't moving meaningfully (< 100 m).
function movement(core, features) {
  const next = features
    .filter((f) => isPredicted(f) && f.properties.kind === core.properties.kind && f.geometry?.type === 'Polygon')
    .sort((a, b) => a.properties.predicted_min - b.properties.predicted_min)[0]
  if (!next) return null
  const from = ringCentroid(core.geometry.coordinates[0])
  const to = ringCentroid(next.geometry.coordinates[0])
  if (distanceKm(from, to) < 0.1) return null
  return compassWord(bearingDeg(from, to))
}

// Nearest current core hazard to the user: how far its edge is, which way it lies,
// and which way it is moving.
export function nearestHazard(user, hazards) {
  const features = hazards?.features ?? []
  let best = null
  for (const f of features) {
    if (!isCurrentCore(f)) continue
    const ring = f.geometry.coordinates[0]
    const inside = pointInRing(user, ring)
    const km = inside ? 0 : Math.min(...ring.map((p) => distanceKm(user, p)))
    if (!best || km < best.km) {
      best = { feature: f, kind: f.properties.kind, km, inside, direction: compassWord(bearingDeg(user, ringCentroid(ring))) }
    }
  }
  if (best) best.moving = movement(best.feature, features)
  return best
}

const KIND_NAME = { wildfire: 'wildfire', tornado: 'tornado', flood: 'flood' }
const KIND_NOUN = { wildfire: 'Fire', tornado: 'Tornado', flood: 'Flooding' }

// "Fire is 2.4 km west of you, moving east." from nearestHazard().
export function hazardSentence(near) {
  if (!near) return null
  if (near.inside) return `You are inside the ${KIND_NAME[near.kind] ?? 'hazard'} zone. Leave now.`
  const moving = near.moving ? `, moving ${near.moving}` : ''
  return `${KIND_NOUN[near.kind] ?? 'Hazard'} is ${near.km.toFixed(1)} km ${near.direction} of you${moving}.`
}
