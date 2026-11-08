// Forecast "who gets cut off next" — shelters that are still clear now but land
// inside a future evacuation ring from GET /forecast. Names the first one so
// the banner can warn neighbourhoods before the fire arrives.

import { dangerRings, unsafeShelterIds } from './evacuation.js'

/**
 * @returns {{ t_min: number, shelter_id: string, name: string, message: string } | null}
 */
export function nextCutoff(shelters, hazards, forecast) {
  const outlines = [...(forecast?.outlines ?? [])].sort((a, b) => (a.t_min ?? 0) - (b.t_min ?? 0))
  if (!shelters?.features?.length || outlines.length === 0) return null

  const nowUnsafe = unsafeShelterIds(shelters, dangerRings(hazards, []))
  for (const outline of outlines) {
    const soon = unsafeShelterIds(shelters, dangerRings(hazards, [outline]))
    for (const id of soon) {
      if (nowUnsafe.has(id)) continue
      const feat = shelters.features.find((f) => f.id === id)
      const name = feat?.properties?.name ?? 'A reception centre'
      const t = outline.t_min ?? outline.properties?.t_min ?? 0
      return {
        t_min: t,
        shelter_id: id,
        name,
        message: `${name} cut off by T+${t} — leave that area now`,
      }
    }
  }
  return null
}

/** Sum of mid-trip route_id changes reported on phone heartbeats. */
export function phoneRerouteCount(evacuees) {
  return (evacuees?.features ?? []).reduce((n, f) => n + (f.properties?.reroutes ?? 0), 0)
}
