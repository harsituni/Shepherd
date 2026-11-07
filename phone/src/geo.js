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

// Nearest core hazard to the user: how far its edge is and which way it lies.
export function nearestHazard(user, hazards) {
  let best = null
  for (const f of hazards?.features ?? []) {
    if (f.properties?.zone !== 'core' || f.geometry?.type !== 'Polygon') continue
    const ring = f.geometry.coordinates[0]
    const inside = pointInRing(user, ring)
    const km = inside ? 0 : Math.min(...ring.map((p) => distanceKm(user, p)))
    if (!best || km < best.km) {
      best = { kind: f.properties.kind, km, inside, direction: compassWord(bearingDeg(user, ringCentroid(ring))) }
    }
  }
  return best
}
