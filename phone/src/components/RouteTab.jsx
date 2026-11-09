import { isCurrentCore, isPredicted } from '../geo.js'
import { dangerRings, evacZones, unsafeShelterIds } from '../evacuation.js'
import { clockTime } from '../leaveBy.js'
import { ChevronUpIcon, PinIcon, RerouteIcon } from './icons.jsx'
import EvacuateControls, { MODES } from './EvacuateControls.jsx'
import RouteOptions, { STATUS, clearLine } from './RouteOptions.jsx'

function percentFull(shelters, shelterId) {
  const s = shelters?.features?.find((f) => f.id === shelterId)
  if (!s?.properties?.capacity) return null
  return Math.round((s.properties.occupancy / s.properties.capacity) * 100)
}

function formatKm(km) {
  if (km == null || Number.isNaN(Number(km))) return '–'
  return (Math.round(Number(km) * 10) / 10).toFixed(1)
}

// Routes run between road points (shared/route_v3.md): metres from the person to
// where the route starts, and from where it ends to the centre. Not mapped, so
// these are notes, never directions. Null when there's no gap worth mentioning.
const GAP_M = 10
function gaps(route) {
  const from = route?.access?.origin?.unmodeled_m
  const to = route?.access?.destination?.unmodeled_m
  return {
    start: from >= GAP_M ? Math.round(from) : null,
    end: to >= GAP_M ? Math.round(to) : null,
  }
}

function lostLine(lost, route) {
  const why = lost.status === 'blocked' ? 'is now blocked' : "can't be confirmed safe any more"
  const instead = route.shelter_name ? ` Showing ${route.shelter_name} instead.` : ''
  return `Your route to ${lost.shelter_name} ${why}.${instead}`
}

// One-row key for what's actually drawn on the map right now.
export function MapKey({ hazards, shelters, route, location, reports }) {
  const features = hazards?.features ?? []
  const evac = evacZones(hazards).features.length > 0
  const outlines = hazards?.forecast ?? features.filter(isPredicted)
  const anyUnsafe = unsafeShelterIds(shelters, dangerRings(hazards, outlines)).size > 0
  const items = [
    features.some(isCurrentCore) && ['swatch-hazard', 'Hazard now'],
    evac && ['swatch-evac', 'Evacuation zone'],
    features.some(isPredicted) && ['swatch-predicted', 'Predicted spread'],
    route?.geometry && ['swatch-route', 'Your route'],
    route?.options?.length > 1 && ['swatch-alt', 'Other routes'],
    ['swatch-shelter', 'Shelter'],
    anyUnsafe && ['swatch-shelter-unsafe', 'Unsafe shelter'],
    location && ['swatch-you', 'You'],
    reports?.features?.length > 0 && ['swatch-report', 'Reported hazard'],
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

// The route/shelter details for the current state (no location, errors, options,
// evacuating…). Shared by the classic Route tab and the map-first layouts.
export function RouteDetails({
  location,
  route,
  lost,
  routeError,
  shelters,
  onChoose,
  trip,
  evacMode,
  onEvacMode,
  onStartEvacuating,
  onStopEvacuating,
}) {
  const controls = (
    <EvacuateControls
      route={route}
      trip={trip}
      mode={evacMode}
      onMode={onEvacMode}
      onStart={onStartEvacuating}
      onStop={onStopEvacuating}
    />
  )

  let details
  if (trip) {
    // Evacuating: progress + Stop. The turn banner floats on the map; no turn line
    // here above the drive controls. Mid-trip reroutes show why.
    const rerouteLine = trip.notice || route?.reroute_reason
    details = (
      <>
        {rerouteLine && (
          <div className="notice notice-strong" role="status">
            <RerouteIcon />
            <span>Rerouted: {rerouteLine}</span>
          </div>
        )}
        {controls}
      </>
    )
  } else if (!location) {
    details = (
      <div className="notice">
        <PinIcon />
        <span>
          Tap the map where you are. Shepherd finds the safest route to an open shelter and updates it as conditions
          change.
        </span>
      </div>
    )
  } else if (routeError === 'out_of_area') {
    details = (
      <div className="notice" role="status">
        <PinIcon />
        <span>
          Can&apos;t route from here. Tap closer to central Edmonton (near the shelters) and try
          again.
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
  } else if (routeError && !route) {
    details = (
      <div className="notice">
        <span>Can't reach Shepherd right now. Retrying…</span>
      </div>
    )
  } else if (!route) {
    details = <p className="muted">Finding your route…</p>
  } else if (route.options?.length) {
    const { start } = gaps(route)
    details = (
      <>
        {route.no_safe_route === true && (
          <div className="no-route" role="alert">
            <strong>No safe route found</strong>
            <span>Every route below is forecast to be cut by fire. Stay where you are if it is safe and call 911.</span>
            <a className="btn-primary" href="tel:911">
              Call 911
            </a>
          </div>
        )}
        {route.route_status === 'indeterminate' && (
          <div className="notice notice-strong" role="status">
            <span>
              Shepherd can&apos;t confirm a safe route right now. Follow official instructions, and call 911 if you are
              in danger.
            </span>
          </div>
        )}
        {lost && (
          <div className="notice notice-strong" role="status">
            <RerouteIcon />
            <span>{lostLine(lost, route)}</span>
          </div>
        )}
        <RouteOptions
          options={route.options}
          bestId={route.best_route_id}
          chosenId={route.route_id}
          shelters={shelters}
          onChoose={onChoose}
        />
        {start != null && <p className="muted num">Route starts on the road {start} m from you.</p>}
        {route.geometry && controls}
      </>
    )
  } else {
    const full = percentFull(shelters, route.shelter_id)
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
            <strong>{route.eta_min} min</strong> · {formatKm(route.distance_km)} km
            {full != null && ` · ${full}% full`}
          </span>
        </div>
        {controls}
      </>
    )
  }

  return details
}

// Extra detail for the picked route, below the fold of the map-first route panel:
// you scroll the panel down to read it. Only facts the backend sends (shelter
// capacity and status, the route's forecast status, leave-by, directions).
export function RouteMore({ route, shelters, trip, evacMode, deadline }) {
  if (trip || !route?.shelter_id) return null
  const option =
    route.options?.find((o) => o.id === route.route_id) ?? route.options?.find((o) => o.shelter_id === route.shelter_id)
  const shelter = shelters?.features?.find((f) => f.id === route.shelter_id)?.properties
  const cap = shelter?.capacity
  const free = cap != null ? Math.max(0, cap - (shelter.occupancy ?? 0)) : null
  const status = option ? STATUS[option.status] ?? STATUS.indeterminate : null
  const statusLine = option ? clearLine(option) ?? status.hint : null
  const steps = route.steps ?? []
  const approximate = option?.approximate ?? route.approximate
  const mode = MODES.find(([m]) => m === evacMode)
  const { start, end } = gaps(option ?? route)

  return (
    <section className="route-more" aria-label="Route details">
      <h3 className="route-more-head">
        Route details
        <ChevronUpIcon aria-hidden="true" />
      </h3>
      <dl className="route-more-list">
        <div>
          <dt>Shelter</dt>
          <dd>
            <strong>{route.shelter_name}</strong>
            {shelter && <span>{shelter.open === false ? 'Closed' : 'Open now'}</span>}
            {free != null && (
              <span className="num">
                {free.toLocaleString()} of {cap.toLocaleString()} spaces free
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>Trip</dt>
          <dd className="num">
            <strong>{route.eta_min} min</strong>
            <span>{formatKm(route.distance_km)} km by car</span>
            {start != null && <span>Starts on the road {start} m from you</span>}
            {end != null && <span>Ends on the road {end} m from the centre</span>}
            {(start != null || end != null) && <span>Those short stretches aren&apos;t mapped.</span>}
          </dd>
        </div>
        {status && (
          <div>
            <dt>Fire forecast</dt>
            <dd>
              <span className={`route-more-status status-${option.status}`}>
                <span className="status-swatch" aria-hidden="true" />
                {status.label}
              </span>
              {statusLine && <span>{statusLine}</span>}
            </dd>
          </div>
        )}
        {deadline && route.at_risk !== false && (
          <div>
            <dt>Leave by</dt>
            <dd className="num">
              <strong>{clockTime(deadline.atMs)}</strong>
              <span>30 min before the evacuation zone reaches you, or sooner for your route</span>
            </dd>
          </div>
        )}
        {steps.length > 0 && (
          <div>
            <dt>Directions</dt>
            <dd>
              <ol className="route-more-steps">
                {steps.map((st, i) => (
                  <li key={i}>
                    <span>{st.instruction}</span>
                    <span className="num">{formatKm(st.distance_km)} km</span>
                  </li>
                ))}
              </ol>
            </dd>
          </div>
        )}
        {mode && (
          <div>
            <dt>{mode[1]}</dt>
            <dd>
              <span>{mode[2]}</span>
            </dd>
          </div>
        )}
      </dl>
      {approximate && (
        <p className="route-more-note">
          Distance and time are straight-line estimates, not turn-by-turn directions. Follow road signs and responders.
        </p>
      )}
    </section>
  )
}
