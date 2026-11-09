// Timeline slider support. The backend keeps no history (only the hazard "now" and
// a forecast), so the dashboard records a snapshot of /hazards at each poll and
// rebuilds any past minute from them. Minutes after "now" come from /forecast.
// Shapes are blended point by point between the two nearest snapshots, so the
// fire grows and shrinks smoothly even at 16× (one poll ≈ 30 sim minutes).

const isPredicted = (f) => f.properties?.predicted_min != null

// Which forecast outline is drawn as the predicted path while following live.
// Just one: two nested dotted rings (30 + 60) read as a doubled border.
const FORECAST_MIN_SHOWN = [60]

// ---------- shape blending ----------

function lerpRing(a, b, f) {
  if (a.length !== b.length) return f < 0.5 ? a : b
  return a.map(([x, y], i) => [x + (b[i][0] - x) * f, y + (b[i][1] - y) * f])
}

function lerpGeometry(a, b, f) {
  if (a?.type !== 'Polygon' || b?.type !== 'Polygon') return f < 0.5 ? a : b
  if (a.coordinates.length !== b.coordinates.length) return f < 0.5 ? a : b
  return { type: 'Polygon', coordinates: a.coordinates.map((ring, i) => lerpRing(ring, b.coordinates[i], f)) }
}

// Blend two lists of features matched by id. A feature only in one list shows
// once the blend is past halfway toward that list.
function lerpFeatures(a, b, f) {
  const byId = new Map(a.map((x) => [x.id, x]))
  const out = []
  for (const fb of b) {
    const fa = byId.get(fb.id)
    byId.delete(fb.id)
    if (fa) out.push({ ...fb, geometry: lerpGeometry(fa.geometry, fb.geometry, f) })
    else if (f >= 0.5) out.push(fb)
  }
  if (f < 0.5) out.push(...byId.values())
  return out
}

// ---------- recording ----------

// snapshots: Map<sim_time, features[]> of the current (non-predicted) hazard.
export function recordSnapshot(snapshots, hazards, simState) {
  const t = hazards?.sim_time
  if (t == null || !simState || simState.state === 'idle') return
  // A new run starts back at a lower sim_time: forget the old one.
  const latest = Math.max(-1, ...snapshots.keys())
  if (t < latest) snapshots.clear()
  snapshots.set(t, (hazards.features ?? []).filter((f) => !isPredicted(f)))
}

// ---------- reading ----------

// The hazard at past minute t, blended between the snapshots either side of it.
function pastFeatures(snapshots, t) {
  const times = [...snapshots.keys()].sort((x, y) => x - y)
  if (times.length === 0) return []
  if (t <= times[0]) return snapshots.get(times[0])
  for (let i = 1; i < times.length; i++) {
    if (t <= times[i]) {
      const [t0, t1] = [times[i - 1], times[i]]
      return lerpFeatures(snapshots.get(t0), snapshots.get(t1), (t - t0) / (t1 - t0))
    }
  }
  return snapshots.get(times[times.length - 1])
}

// The hazard `ahead` minutes after now: the current core blended toward the
// forecast outlines (15, 30 … 120), drawn as if it were the fire at that time.
function futureFeatures(current, forecast, ahead) {
  const core = current.find((f) => f.properties?.zone === 'core')
  const outlines = [...(forecast?.outlines ?? [])].sort((x, y) => x.t_min - y.t_min)
  if (!core || outlines.length === 0) return current
  const steps = [{ t_min: 0, geometry: core.geometry }, ...outlines]
  let geometry = steps[steps.length - 1].geometry
  for (let i = 1; i < steps.length; i++) {
    if (ahead <= steps[i].t_min) {
      const [s0, s1] = [steps[i - 1], steps[i]]
      geometry = lerpGeometry(s0.geometry, s1.geometry, (ahead - s0.t_min) / (s1.t_min - s0.t_min))
      break
    }
  }
  return [{ ...core, id: `${core.id}:forecast`, properties: { ...core.properties, forecast: true }, geometry }]
}

// The forecast's 30 / 60 min outlines as predicted-path features (`predicted_min`).
function predictedFeatures(forecast) {
  return (forecast?.outlines ?? [])
    .filter((o) => FORECAST_MIN_SHOWN.includes(o.t_min) && o.geometry)
    .map((o) => ({ type: 'Feature', id: o.id, properties: { ...o.properties, predicted_min: o.t_min }, geometry: o.geometry }))
}

// How far ahead the slider can go: the forecast horizon, if there is a forecast.
export function forecastHorizon(forecast) {
  return Math.max(0, ...(forecast?.outlines ?? []).map((o) => o.t_min))
}

// What the map should draw. viewing = null follows live (hazard now + predicted
// rings); otherwise it's the sim minute picked on the slider, past or future.
export function hazardsForView(hazards, forecast, snapshots, viewing) {
  if (!hazards) return hazards
  const now = hazards.sim_time ?? 0
  const current = (hazards.features ?? []).filter((f) => !isPredicted(f))
  if (viewing == null) return { ...hazards, features: [...predictedFeatures(forecast), ...current] }
  const features = viewing < now ? pastFeatures(snapshots, viewing) : futureFeatures(current, forecast, viewing - now)
  return { ...hazards, sim_time: viewing, features }
}
