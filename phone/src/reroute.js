// Mid-trip rerouting: decide when the live /route answer means we should leave
// the path we're driving and take another, and build a short reason for the UI.
// Demo rule: whenever a better usable recommendation exists, take it so judges
// see Shepherd actively helping people off jammed / unsafe roads.

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
  const saves = (currentOpt?.eta_min ?? 0) - (next.eta_min ?? 0)
  const delay = currentOpt?.traffic_delay_min ?? 0
  if (delay > 0 || saves >= 1) {
    return saves >= 1
      ? `Traffic: faster route saves ${Math.max(1, Math.round(saves))} min`
      : 'Traffic: clearing a jam on your route'
  }
  return 'Taking a safer path'
}

/**
 * If the person should leave their current drive for a new recommendation,
 * returns { route, reason }. Otherwise null.
 *
 * Always hop onto the current best usable option when it differs from the path
 * we're driving — hazard growth, closed roads, and traffic jams all surface as
 * a visible mid-trip reroute (judge demo).
 */
export function shouldReroute(trip, routeBody) {
  if (!trip?.route || trip.arrived || !routeBody) return null
  const currentId = trip.route.route_id ?? trip.route.id
  if (!currentId) return null

  const current = optionOf(routeBody, currentId)
  const best = optionOf(routeBody, routeBody.best_route_id)
  if (!best || !usable(best)) return null
  if (best.id === currentId) return null

  const next = flattenOption(routeBody, best)
  if (!next?.geometry) return null
  return { route: next, reason: shortReason(trip.route, next, current) }
}

/** True when /route says nothing left is safe to drive. */
export function noSafeRoute(routeBody) {
  return routeBody?.no_safe_route === true || (routeBody?.route_status === 'blocked' && !routeBody?.best_route_id)
}
