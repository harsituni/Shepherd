import { hazardSentence } from '../geo.js'
import { formatMinSec, useSimNow } from '../simClock.js'
import { WarningIcon } from './icons.jsx'

// The first thing on screen during a wildfire: "Wildfire — evacuate" with the
// leave-by countdown as the largest text. Leave-by comes from GET /route (contract
// v2 `leave_by_sim_min`), counted down on the sim clock, so it follows the
// dashboard's 1× / 4× / 16× speed and stops when the sim is paused.
export default function EvacCard({ location, route, routeError, near, clock }) {
  const simNow = useSimNow(clock)
  const leaveBy = route?.leave_by_sim_min
  const paused = clock?.state === 'paused'
  const where = route?.shelter_name ? `${route.shelter_name}, ${route.eta_min} min drive` : null

  let label = null // small line above the big text
  let big // the largest text on screen
  let lines = [] // supporting lines under it
  let spoken // what screen readers hear (changes at most once a minute)

  if (!location) {
    big = 'Tap the map where you are'
    lines = ["We'll tell you when you need to leave."]
    spoken = `Wildfire. Evacuate. ${big}.`
  } else if (routeError === 'no_route') {
    big = 'No safe route'
    lines = ['Stay where you are if it is safe and call 911.']
    spoken = `Wildfire. ${big}. Call 911.`
  } else if (near?.inside) {
    big = 'Leave now'
    lines = ['You are inside the wildfire zone.', where]
    spoken = 'Wildfire. You are inside the fire zone. Leave now.'
  } else if (!route) {
    big = routeError ? 'Reconnecting…' : 'Working it out…'
    lines = [routeError ? "Can't reach Shepherd right now." : 'Finding when you need to leave.']
    spoken = `Wildfire. Evacuate. ${lines[0]}`
  } else if (leaveBy == null) {
    // Backend still on the Step 0 /route shape: no leave-by time to count down.
    big = 'Leave as soon as you can'
    lines = [where, hazardSentence(near)]
    spoken = `Wildfire. Evacuate. ${big}.`
  } else {
    const left = simNow == null ? leaveBy - (route.sim_time ?? leaveBy) : leaveBy - simNow
    if (left <= 0) {
      big = 'Leave now'
      lines = [`Your leave-by time, T+${leaveBy}, has passed.`, where]
      spoken = 'Wildfire. Your leave-by time has passed. Leave now.'
    } else {
      label = 'Leave within'
      big = formatMinSec(left)
      lines = [`Leave by T+${leaveBy}${paused ? ' · simulation paused' : ''}`, where, hazardSentence(near)]
      const mins = Math.ceil(left)
      spoken = `Wildfire. Evacuate. Leave within ${mins} ${mins === 1 ? 'minute' : 'minutes'}.`
    }
  }

  const urgent = big === 'Leave now' || big === 'No safe route'

  return (
    <section className={`evac${urgent ? ' evac-urgent' : ''}`} aria-labelledby="evac-title">
      <div className="evac-head">
        <WarningIcon className="evac-icon" />
        <h1 className="evac-title" id="evac-title">
          Wildfire — evacuate
        </h1>
      </div>
      <div className="evac-body" aria-hidden="true">
        {label && <span className="evac-label">{label}</span>}
        <span className={`evac-big num${big.length > 10 ? ' evac-big-words' : ''}`}>{big}</span>
        {lines.filter(Boolean).map((l) => (
          <span key={l} className="evac-line num">
            {l}
          </span>
        ))}
      </div>
      <p className="sr-only" aria-live={urgent ? 'assertive' : 'polite'}>
        {spoken}
      </p>
    </section>
  )
}
