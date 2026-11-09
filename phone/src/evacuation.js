// Evacuation zones and unsafe shelters, computed client-side from the fire shapes.
// Keep in step with dashboard/src/evacuation.js (same rule on both surfaces).
//
// - Evacuation zone: a circle around each wildfire as it is now (never the
//   predicted path), centred on the fire, reaching EVAC_BUFFER_M past its farthest
//   edge, so it always covers the whole fire and grows only as the fire grows. It is
//   built from whatever fire shape is drawn, so it follows the history slider.
// - Unsafe shelter: inside the evacuation circle of the fire now or of any forecast
//   outline (GET /forecast, up to +120 min), i.e. the fire is there or will come
//   close enough to put the shelter inside an evacuation zone.

const EVAC_BUFFER_M = 1000
export const UNSAFE_SHELTER_TEXT = 'Unsafe: Find another shelter'

const M_PER_DEG_LAT = 111320
const CIRCLE_STEPS = 64

function centroid(ring) {
  const pts = ring.length > 1 ? ring.slice(0, -1) : ring
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length]
}

// A circle (closed ring, metres-true) centred on the ring's centre, with radius =
// its farthest vertex + `margin` metres.
function evacCircle(ring, margin = EVAC_BUFFER_M) {
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

const isHazardNow = (f) =>
  (f.properties?.kind === 'wildfire' || f.properties?.kind === 'tornado') &&
  f.properties?.zone === 'core' &&
  f.properties?.predicted_min == null &&
  f.geometry?.type === 'Polygon'

// One evacuation circle per active core hazard (wildfire or tornado funnel).
export function evacZones(hazards) {
  const features = (hazards?.features ?? []).filter(isHazardNow).map((f) => ({
    type: 'Feature',
    id: `${f.id}:evac`,
    properties: { fire_id: f.id },
    geometry: { type: 'Polygon', coordinates: [evacCircle(f.geometry.coordinates[0])] },
  }))
  return { type: 'FeatureCollection', features }
}

// Circles / rings that count for shelter safety: around the hazard now and every
// forecast outline. Tornado forecasts are long corridors — wrapping those in
// evacCircle() would paint a city-sized disc around the corridor centroid.
export function dangerRings(hazards, forecastOutlines = []) {
  const now = (hazards?.features ?? []).filter(isHazardNow).map((f) => evacCircle(f.geometry.coordinates[0]))
  const forecast = forecastOutlines
    .filter((o) => o.geometry?.type === 'Polygon')
    .map((o) =>
      o.properties?.kind === 'tornado' ? o.geometry.coordinates[0] : evacCircle(o.geometry.coordinates[0]),
    )
  return [...now, ...forecast]
}

// Ids of shelters inside any danger circle.
export function unsafeShelterIds(shelters, rings) {
  const ids = new Set()
  for (const s of shelters?.features ?? []) {
    if (rings.some((ring) => pointInRing(s.geometry.coordinates, ring))) ids.add(s.id)
  }
  return ids
}

// Match the dashboard: never keep a yellow-zone centre as Clear / Recommended,
// even if /route briefly still says ok (road cell clear, building in the circle).
export function demoteUnsafeRoute(route, unsafeIds) {
  if (!route?.options?.length || !unsafeIds?.size) return route
  const options = route.options.map((o) => {
    if (!unsafeIds.has(o.shelter_id) || (o.status !== 'ok' && o.status !== 'tight')) return o
    const name = o.shelter_name || 'this shelter'
    return {
      ...o,
      status: 'blocked',
      leave_by_sim_min: null,
      clear_until_sim_min: null,
      clear_until_label: null,
      reason: `Fire is already near ${name} (inside the evacuation zone).`,
    }
  })
  const usable = (o) => o.status === 'ok' || o.status === 'tight'
  const best = options.find((o) => usable(o) && o.id === route.best_route_id) ?? options.find(usable)
  const leaveBy = best?.leave_by_sim_min ?? null
  const sim = route.sim_time ?? 0
  return {
    ...route,
    options,
    best_route_id: best?.id ?? null,
    route_status: best ? 'viable' : options.some((o) => o.status === 'indeterminate') ? 'indeterminate' : 'blocked',
    no_safe_route: best ? false : options.some((o) => o.status === 'indeterminate') ? null : true,
    leave_by_sim_min: leaveBy,
    leave_by_label: leaveBy == null ? null : `Leave within ${Math.max(0, leaveBy - sim)} min (sim)`,
    ...(best
      ? {
          shelter_id: best.shelter_id,
          shelter_name: best.shelter_name,
          distance_km: best.distance_km,
          eta_min: best.eta_min,
          geometry: best.geometry,
          status: best.status,
          margin_min: best.margin_min,
          reason: best.reason,
          route_id: best.id,
        }
      : {
          shelter_id: undefined,
          shelter_name: undefined,
          distance_km: undefined,
          eta_min: undefined,
          geometry: undefined,
          status: undefined,
          margin_min: undefined,
          reason: undefined,
          route_id: null,
        }),
  }
}
