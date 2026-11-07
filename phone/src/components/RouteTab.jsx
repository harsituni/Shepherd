import { isCurrentCore, isPredicted } from '../geo.js'
import { PinIcon, RerouteIcon, TurnIcon } from './icons.jsx'
import RouteOptions from './RouteOptions.jsx'

function percentFull(shelters, shelterId) {
  const s = shelters?.features?.find((f) => f.id === shelterId)
  if (!s?.properties?.capacity) return null
  return Math.round((s.properties.occupancy / s.properties.capacity) * 100)
}

// One-row key for what's actually drawn on the map right now.
function MapKey({ hazards, route, location }) {
  const features = hazards?.features ?? []
  const items = [
    features.some(isCurrentCore) && ['swatch-hazard', 'Hazard now'],
    features.some(isPredicted) && ['swatch-predicted', 'Predicted spread'],
    route?.geometry && ['swatch-route', 'Your route'],
    route?.options?.length > 1 && ['swatch-alt', 'Other routes'],
    ['swatch-shelter', 'Shelter'],
    location && ['swatch-you', 'You'],
  ].filter(Boolean)
  return (
    <ul className="map-key" aria-label="Map key">
      {items.map(([swatch, label]) => (
        <li key={label}>
          <span className={`swatch ${swatch}`} aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  )
}

export default function RouteTab({
  map,
  hazards,
  location,
  route,
  lost,
  routeError,
  shelters,
  onChoose,
  onStartNavigation,
}) {
  let details
  if (!location) {
    details = (
      <div className="notice">
        <PinIcon />
        <span>
          Tap the map where you are. Shepherd finds the safest route to an open shelter and updates it as conditions
          change.
        </span>
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
  } else if (route.options?.length) {
    const next = route.steps?.[0]
    details = (
      <>
        {lost && (
          <div className="notice notice-strong" role="status">
            <RerouteIcon />
            <span>
              Your route to {lost.shelter_name} is now blocked. Showing {route.shelter_name} instead.
            </span>
          </div>
        )}
        <RouteOptions
          options={route.options}
          bestId={route.best_route_id}
          chosenId={route.route_id}
          shelters={shelters}
          onChoose={onChoose}
        />
        {next && (
          <div className="next-turn">
            <TurnIcon />
            <div className="next-turn-text">
              <span className="next-turn-title">{next.instruction}</span>
              <span className="muted num">in {next.distance_km} km</span>
            </div>
          </div>
        )}
        <button type="button" className="btn-primary" onClick={onStartNavigation}>
          Start navigation
        </button>
      </>
    )
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
          <span className="shelter-name">{route.shelter_name}</span>
          <span className="trip num">
            <strong>{route.eta_min} min</strong> · {route.distance_km} km{full != null && ` · ${full}% full`}
          </span>
        </div>
        {next && (
          <div className="next-turn">
            <TurnIcon />
            <div className="next-turn-text">
              <span className="next-turn-title">{next.instruction}</span>
              <span className="muted num">in {next.distance_km} km</span>
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
      <MapKey hazards={hazards} route={route} location={location} />
      <div className="route-details">{details}</div>
    </>
  )
}
