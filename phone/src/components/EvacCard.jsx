import { hazardSentence } from '../geo.js'
import { formatMinSec, useSimNow } from '../simClock.js'
import { WarningIcon } from './icons.jsx'

// The first thing on screen during a wildfire: "Wildfire evacuation" with the
// leave-by countdown as the largest text. Leave-by comes from GET /route
// (`leave_by_sim_min`), counted down on the sim clock, so it follows the
// dashboard's 1× / 4× / 16× speed and stops when the sim is paused.
// Already evacuating: "Leave now" no longer applies, so don't repeat it.
const onTheWay = (near) =>
  near?.inside
    ? near.kind === 'tornado'
      ? `You're in the ${near.feature?.properties?.ef_label ?? 'tornado'} path. Keep going.`
      : "You're in the fire zone. Keep going."
    : hazardSentence(near)

export default function EvacCard({ location, route, routeError, near, clock, trip }) {
  const simNow = useSimNow(clock)
  const leaveBy = route?.leave_by_sim_min
  const paused = clock?.state === 'paused'
  const where = route?.shelter_name ? `${route.shelter_name}, ${route.eta_min} min drive` : null
  const ef = near?.feature?.properties?.ef_label
  const kindWord = near?.kind === 'tornado' ? (ef ? `${ef} tornado` : 'Tornado') : 'Wildfire'
  const title =
    near?.kind === 'tornado' ? `${ef ? `${ef} ` : ''}Tornado evacuation (beta)` : 'Wildfire evacuation'

  let label = null // small line above the big text
  let big // the largest text on screen
  let lines = [] // supporting lines under it
  let spoken // what screen readers hear (changes at most once a minute)

  if (!location) {
    big = 'Tap the map where you are'
    lines = ["We'll tell you when you need to leave."]
    spoken = `${kindWord}. Evacuate. ${big}.`
  } else if (trip?.arrived) {
    big = 'Arrived'
    lines = [`You're at ${trip.route.shelter_name}.`]
    spoken = `You have arrived at ${trip.route.shelter_name}.`
  } else if (trip?.mode === 'sim') {
    // Simulated drive (issue #56): count down to arrival instead of to leave-by.
    const left = trip.route.eta_min * (1 - (trip.fraction ?? 0))
    label = 'Arriving in'
    big = formatMinSec(left)
    lines = [`Driving to ${trip.route.shelter_name} (simulated)`]
    if (trip.notice) lines.push(`Rerouted: ${trip.notice}`)
    lines.push(onTheWay(near))
    const mins = Math.max(1, Math.ceil(left))
    spoken = trip.notice
      ? `Rerouted. Evacuating to ${trip.route.shelter_name}.`
      : `Evacuating. Arriving at ${trip.route.shelter_name} in about ${mins} ${mins === 1 ? 'minute' : 'minutes'}.`
  } else if (trip?.mode === 'gps') {
    big = 'On your way'
    lines = [`Heading to ${trip.route.shelter_name}`, 'Following your real GPS.']
    if (trip.notice) lines.push(`Rerouted: ${trip.notice}`)
    lines.push(onTheWay(near))
    spoken = trip.notice
      ? `Rerouted. Evacuating to ${trip.route.shelter_name}.`
      : `Evacuating to ${trip.route.shelter_name}.`
  } else if (routeError === 'no_route' || route?.no_safe_route === true) {
    big = 'No safe route'
    lines = ['Stay where you are if it is safe and call 911.']
    spoken = `${kindWord}. ${big}. Call 911.`
  } else if (route?.route_status === 'indeterminate') {
    // v3: nothing could be confirmed safe or unsafe, so nothing is recommended.
    big = "Can't confirm"
    lines = ["Shepherd can't confirm a safe route right now.", 'Follow official instructions. Call 911 if you are in danger.']
    spoken = `${kindWord}. ${lines[0]} ${lines[1]}`
  } else if (near?.inside) {
    big = 'Leave now'
    lines = [near.kind === 'tornado' ? 'You are inside the tornado path.' : 'You are inside the wildfire zone.', where]
    spoken = `${kindWord}. You are inside the hazard zone. Leave now.`
  } else if (!route) {
    big = routeError ? 'Reconnecting…' : 'Working it out…'
    lines = [routeError ? "Can't reach Shepherd right now." : 'Finding when you need to leave.']
    spoken = `${kindWord}. Evacuate. ${lines[0]}`
  } else if (leaveBy == null && route.options) {
    // No leave-by: the hazard isn't forecast to reach this route, so no deadline yet.
    big = 'No deadline yet'
    lines = [
      near?.kind === 'tornado'
        ? "The tornado isn't forecast to reach your route."
        : "The fire isn't forecast to reach your route.",
      where,
      hazardSentence(near),
    ]
    spoken = `${kindWord}. ${lines[0]}`
  } else if (leaveBy == null) {
    // Backend still on the Step 0 /route shape: no leave-by time to count down.
    big = 'Leave as soon as you can'
    lines = [where, hazardSentence(near)]
    spoken = `${kindWord}. Evacuate. ${big}.`
  } else {
    const left = simNow == null ? leaveBy - (route.sim_time ?? leaveBy) : leaveBy - simNow
    if (left <= 0) {
      big = 'Leave now'
      lines = [`Your leave-by time, T+${leaveBy}, has passed.`, where]
      spoken = `${kindWord}. Your leave-by time has passed. Leave now.`
    } else {
      label = 'Leave within'
      big = formatMinSec(left)
      lines = [`Leave by T+${leaveBy}${paused ? ' · simulation paused' : ''}`, where, hazardSentence(near)]
      const mins = Math.ceil(left)
      spoken = `${kindWord}. Evacuate. Leave within ${mins} ${mins === 1 ? 'minute' : 'minutes'}.`
    }
  }

  const urgent = big === 'Leave now' || big === 'No safe route'

  return (
    <section className={`evac${urgent ? ' evac-urgent' : ''}`} aria-labelledby="evac-title">
      <div className="evac-head">
        <WarningIcon className="evac-icon" />
        <h1 className="evac-title" id="evac-title">
          {title}
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
