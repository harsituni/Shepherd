// Turn-by-turn cues from a route LineString, for the evacuating drive.
// Coordinates are [lon, lat]. No street-name API: bearings decide left/right.

import { bearingDeg, distanceKm } from './geo.js'

const MIN_LEG_M = 25 // ignore tiny jogs when reading a corner
const MIN_TURN_DEG = 35 // straighter than this stays "continue"
const MIN_GAP_M = 80 // don't stack two cues on the same corner

export function routeCoords(geometry) {
  if (!geometry) return []
  if (geometry.type === 'LineString') return geometry.coordinates ?? []
  if (geometry.type === 'MultiLineString') {
    const parts = geometry.coordinates ?? []
    if (!parts.length) return []
    const out = [...parts[0]]
    for (let i = 1; i < parts.length; i++) {
      const part = parts[i]
      if (!part?.length) continue
      const last = out[out.length - 1]
      if (!last || last[0] !== part[0][0] || last[1] !== part[0][1]) out.push(part[0])
      out.push(...part.slice(1))
    }
    return out
  }
  return []
}

function turnLabel(delta) {
  const abs = Math.abs(delta)
  const left = delta < 0
  if (abs >= 150) return left ? 'Make a U-turn' : 'Make a U-turn'
  if (abs >= 120) return left ? 'Sharp left' : 'Sharp right'
  if (abs >= 50) return left ? 'Turn left' : 'Turn right'
  return left ? 'Keep left' : 'Keep right'
}

function turnKind(delta) {
  const abs = Math.abs(delta)
  if (abs >= 150) return 'uturn'
  if (abs >= 50) return delta < 0 ? 'left' : 'right'
  return delta < 0 ? 'slight-left' : 'slight-right'
}

// Signed turn angle at b, going a → b → c (−180..180; negative = left).
function cornerDelta(a, b, c) {
  const inn = bearingDeg(a, b)
  const out = bearingDeg(b, c)
  return ((out - inn + 540) % 360) - 180
}

// Walk far enough along the polyline that the leg is meaningful.
function look(coords, start, dir) {
  let i = start
  let travelled = 0
  while (dir > 0 ? i + 1 < coords.length : i - 1 >= 0) {
    const j = i + dir
    travelled += distanceKm(coords[i], coords[j]) * 1000
    i = j
    if (travelled >= MIN_LEG_M) return i
  }
  return i
}

/** Significant turns along the route, plus a final arrive cue. */
export function turnsAlong(geometry) {
  const coords = routeCoords(geometry)
  if (coords.length < 2) return []

  const turns = []
  let kmAlong = 0
  for (let i = 1; i < coords.length; i++) {
    kmAlong += distanceKm(coords[i - 1], coords[i])
    if (i >= coords.length - 1) break
    const prev = look(coords, i, -1)
    const next = look(coords, i, 1)
    if (prev === i || next === i) continue
    const delta = cornerDelta(coords[prev], coords[i], coords[next])
    if (Math.abs(delta) < MIN_TURN_DEG) continue
    const last = turns[turns.length - 1]
    if (last && (kmAlong - last.kmAlong) * 1000 < MIN_GAP_M) {
      // Keep the sharper of two close corners.
      if (Math.abs(delta) > Math.abs(last.delta)) {
        turns[turns.length - 1] = {
          id: `t${i}`,
          kmAlong,
          instruction: turnLabel(delta),
          kind: turnKind(delta),
          delta,
        }
      }
      continue
    }
    turns.push({
      id: `t${i}`,
      kmAlong,
      instruction: turnLabel(delta),
      kind: turnKind(delta),
      delta,
    })
  }

  turns.push({
    id: 'arrive',
    kmAlong,
    instruction: 'Arrive at shelter',
    kind: 'arrive',
    delta: 0,
  })
  return turns
}

/** Next unannounced turn within `withinM` metres ahead (or just passed). */
export function cueForProgress(turns, kmAlong, announced, withinM = 120) {
  const withinKm = withinM / 1000
  for (const turn of turns) {
    if (announced.has(turn.id)) continue
    const ahead = turn.kmAlong - kmAlong
    // Still ahead within the window, or we just crossed it this tick.
    if (ahead <= withinKm && ahead >= -0.04) {
      const metres = Math.max(0, Math.round(ahead * 1000))
      return {
        ...turn,
        distance_m: metres,
        distanceLabel: metres === 0 ? 'now' : metres < 1000 ? `in ${metres} m` : `in ${(metres / 1000).toFixed(1)} km`,
      }
    }
  }
  return null
}
