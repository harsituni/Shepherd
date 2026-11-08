import { CloseIcon, WarningIcon } from './icons.jsx'

// Issue #58: the big red alert when the route the user is relying on gets worse
// after a wind change (ok -> tight, -> blocked, or dropped). Full width across the
// top of the map, above everything else, with the way out as its one button:
// switch to the best route that's still usable (or call 911 if there is none).
//
// Props:
//   alert        { shelterName, to: 'tight'|'blocked'|'gone', ... } from useRouteWatch
//   alt          best usable option to switch to, or null
//   evacuating   true mid-trip (switching restarts the drive from where you are)
//   onSwitch(alt), onDismiss()

function copy(alert, alt, evacuating) {
  const name = alert.shelterName ?? 'your shelter'
  if (alert.to === 'tight') {
    return {
      title: 'Your route is getting tight',
      line: `Fire is now forecast near your route to ${name}.${alt?.status === 'ok' ? ' A clearer route is open.' : ''}`,
    }
  }
  if (alert.to === 'gone') {
    return { title: 'Your route has changed', line: `${name} is no longer one of your safe options.` }
  }
  if (!alt) {
    return { title: 'No safe route from here', line: 'Stay where you are if it is safe and call 911.' }
  }
  return {
    title: 'Your route is blocked',
    line: `Fire is now forecast on your way to ${name}. ${evacuating ? 'Switch now.' : 'Pick a new route.'}`,
  }
}

export default function RouteAlert({ alert, alt, evacuating, onSwitch, onDismiss }) {
  const { title, line } = copy(alert, alt, evacuating)
  // On a tight route, only offer a switch to something actually clearer.
  const offer = alert.to === 'tight' ? (alt?.status === 'ok' ? alt : null) : alt
  const noWayOut = alert.to !== 'tight' && !alt

  return (
    <section className="route-alert" role="alert" aria-labelledby="route-alert-title">
      <div className="route-alert-head">
        <WarningIcon className="route-alert-icon" />
        <h2 className="route-alert-title" id="route-alert-title">
          {title}
        </h2>
        <button type="button" className="route-alert-close" aria-label="Dismiss route alert" onClick={onDismiss}>
          <CloseIcon />
        </button>
      </div>
      <p className="route-alert-line">{line}</p>
      {offer && (
        <button type="button" className="route-alert-btn num" onClick={() => onSwitch(offer)}>
          <span>
            Switch to {offer.shelter_name}
            {offer.eta_min != null && <span className="route-alert-eta"> · {offer.eta_min} min</span>}
          </span>
        </button>
      )}
      {noWayOut && (
        <a className="route-alert-btn" href="tel:911">
          Call 911
        </a>
      )}
      {alert.to === 'tight' && (
        <button type="button" className="route-alert-keep" onClick={onDismiss}>
          Keep my route
        </button>
      )}
    </section>
  )
}

// Quiet line when route checks keep failing, so a dead connection never looks like
// "all clear". Shown over the map, under the top row.
export function RouteStale({ seconds }) {
  return (
    <p className="route-stale num" role="status">
      Can&apos;t check your route right now.{seconds != null && ` Last checked ${seconds} s ago.`} Retrying…
    </p>
  )
}
