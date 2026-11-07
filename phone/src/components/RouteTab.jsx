import { PinIcon, RerouteIcon, TurnIcon } from './icons.jsx'

function percentFull(shelters, shelterId) {
  const s = shelters?.features?.find((f) => f.id === shelterId)
  if (!s?.properties?.capacity) return null
  return Math.round((s.properties.occupancy / s.properties.capacity) * 100)
}

export default function RouteTab({ map, location, route, routeError, shelters, onStartNavigation }) {
  let details
  if (!location) {
    details = (
      <div className="notice">
        <PinIcon />
        <span>Tap the map to set your location. We'll find the safest route to a shelter.</span>
      </div>
    )
  } else if (routeError === 'no_route') {
    details = (
          <div className="no-route" role="alert">
            <strong>No safe route found</strong>
            <span>Stay where you are if it is safe and call 911.</span>
        <a className="btn-primary" href="tel:911">
          Call 911
        </a>
      </div>
    )
  } else if (routeError) {
    details = (
      <div className="notice">
        <span>Can't reach Shepherd right now. Retrying…</span>
      </div>
    )
  } else if (!route) {
    details = <p className="muted">Finding your route…</p>
  } else {
    const full = percentFull(shelters, route.shelter_id)
    const next = route.steps?.[0]
    details = (
      <>
        {route.rerouted && (
          <div className="notice notice-strong">
            <RerouteIcon />
            <span>Rerouted{route.reroute_reason ? `: ${route.reroute_reason}` : ''}</span>
          </div>
        )}
        <div className="shelter">
          <div className="shelter-info">
            <span className="muted small">Go to shelter</span>
            <span className="shelter-name">{route.shelter_name}</span>
            <span className="muted num">
              {route.distance_km} km{full != null && ` · ${full}% full`}
            </span>
          </div>
          <div className="eta">
            <span className="eta-value num">{route.eta_min}</span>
            <span className="muted small">min</span>
          </div>
        </div>
        {next && (
          <div className="next-turn">
            <TurnIcon />
            <div className="next-turn-text">
              <span className="next-turn-title">{next.instruction}</span>
              <span className="muted small num">in {next.distance_km} km</span>
            </div>
          </div>
        )}
        <button type="button" className="btn-primary" onClick={onStartNavigation}>
          Start navigation
        </button>
      </>
    )
  }

  return (
    <>
      {map}
      <div className="route-details">{details}</div>
    </>
  )
}
