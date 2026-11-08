// Mid-trip rerouting: decide when the live /route answer means we should leave
// the path we're driving and take another, and build a short reason for the UI.

const usable = (o) => o?.status === 'ok' || o?.status === 'tight'

function optionOf(routeBody, id) {
  if (!id || !routeBody?.options) return null
  return routeBody.options.find((o) => o.id === id) ?? null
}

function flattenOption(body, option) {
  if (!option) return null
  return {
    ...body,
    ...option,
    distance_km: option.distance_km,
    id: undefined,
    route_id: option.id,
    best_route_id: body.best_route_id,
    options: body.options,
  }
}

function shortReason(prev, next, currentOpt) {
  if (currentOpt?.status === 'blocked' && /evacuat|already near|shelter/i.test(currentOpt.reason ?? '')) {
    return next.shelter_name && next.shelter_id !== prev.shelter_id
      ? `${prev.shelter_name ?? 'Your shelter'} is unsafe — heading to ${next.shelter_name}`
      : 'Shelter is in the evacuation zone'
  }
  if (currentOpt?.status === 'blocked') {
    return next.shelter_name && next.shelter_id !== prev.shelter_id
      ? `Fire on your route — heading to ${next.shelter_name}`
      : 'Fire on your route — taking a safer path'
  }
  if (currentOpt?.status === 'tight' || currentOpt?.status === 'indeterminate') {
    return next.shelter_name && next.shelter_id !== prev.shelter_id
      ? `Conditions changed — heading to ${next.shelter_name}`
      : 'Conditions changed — taking a safer path'
  }
  if (next.shelter_id !== prev.shelter_id) {
    return `Heading to ${next.shelter_name} instead`
  }
  return 'Taking a safer path'
}

/**
 * If the person should leave their current drive for a new recommendation,
 * returns { route, reason }. Otherwise null.
 *
 * Stay put while the current option is still Clear — avoid thrashing when the
 * backend's ranking jitters. Switch when the current path is gone / blocked /
 * unconfirmed and a usable alternative exists.
 */
export function shouldReroute(trip, routeBody) {
  if (!trip?.route || trip.arrived || !routeBody) return null
  const currentId = trip.route.route_id ?? trip.route.id
  if (!currentId) return null

  const current = optionOf(routeBody, currentId)
  const best = optionOf(routeBody, routeBody.best_route_id)
  if (!best || !usable(best)) return null

  // Still Clear on the same route → keep driving it.
  if (current && usable(current) && current.status === 'ok' && current.id === best.id) return null
  if (current && usable(current) && current.status === 'ok') return null

  // Same usable recommendation (tight is fine to keep if it's still the best).
  if (current && usable(current) && current.id === best.id) return null

  // Current is missing, blocked, indeterminate, or no longer best while unsafe-ish.
  if (current && usable(current) && current.id !== best.id) {
    // Tight but still usable and not the best: only hop if the shelter changed
    // (destination itself is the problem) or margin got much worse.
    if (current.shelter_id === best.shelter_id) return null
  }

  if (best.id === currentId) return null

  const next = flattenOption(routeBody, best)
  if (!next?.geometry) return null
  return { route: next, reason: shortReason(trip.route, next, current) }
}

/** True when /route says nothing left is safe to drive. */
export function noSafeRoute(routeBody) {
  return routeBody?.no_safe_route === true || (routeBody?.route_status === 'blocked' && !routeBody?.best_route_id)
}
