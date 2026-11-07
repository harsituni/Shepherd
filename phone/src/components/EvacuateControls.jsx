import { routeLengthKm } from '../evacuate.js'

// Issue #56: under the route cards. Before leaving: pick Simulated drive (in-room
// demo) or Real GPS, then Start evacuating. While evacuating: progress and Stop.

const MODES = [
  ['sim', 'Simulated drive', 'Moves your dot along the route, so you can demo without walking.'],
  ['gps', 'Real GPS', "Follows your phone's location. Your browser will ask for permission."],
]

export default function EvacuateControls({ route, trip, mode, onMode, onStart, onStop }) {
  if (trip?.arrived) {
    return (
      <div className="trip-status" role="status">
        <strong>You've arrived at {trip.route.shelter_name}.</strong>
        <span className="muted">Tap “I'm safe” below so responders know.</span>
        <button type="button" className="btn-outline" onClick={onStop}>
          Done
        </button>
      </div>
    )
  }

  if (trip) {
    const sim = trip.mode === 'sim'
    const left = 1 - (trip.fraction ?? 0)
    const km = routeLengthKm(trip.route.geometry?.coordinates) * left
    return (
      <div className="trip-status" role="status">
        <strong>
          {sim ? 'Driving' : 'Heading'} to {trip.route.shelter_name}
        </strong>
        {sim ? (
          <>
            <span className="num">
              About {Math.max(1, Math.ceil(trip.route.eta_min * left))} min · {km.toFixed(1)} km left (simulated drive)
            </span>
            <span className="trip-bar" aria-hidden="true">
              <span style={{ width: `${Math.round((trip.fraction ?? 0) * 100)}%` }} />
            </span>
          </>
        ) : (
          <span>Following your phone's location (real GPS).</span>
        )}
        <span className="muted">Responders can see your position while you evacuate.</span>
        <button type="button" className="btn-outline" onClick={onStop}>
          Stop
        </button>
      </div>
    )
  }

  const hint = MODES.find(([m]) => m === mode)?.[2]
  return (
    <div className="evacuate-controls">
      <div className="segmented" role="radiogroup" aria-label="How to evacuate">
        {MODES.map(([m, label]) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => onMode(m)}>
            {label}
          </button>
        ))}
      </div>
      <p className="muted">{hint}</p>
      <button type="button" className="btn-primary" disabled={!route?.geometry} onClick={onStart}>
        Start evacuating
      </button>
    </div>
  )
}
