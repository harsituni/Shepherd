import { evacueeId, routeLengthKm } from '../evacuate.js'

// Issue #56: under the route cards. Before leaving: pick Simulated drive (in-room
// demo) or Real GPS, then Start evacuating. While evacuating: progress and Stop.

export const MODES = [
  ['sim', 'Simulated drive', 'Moves your dot along the route, so you can demo without walking.'],
  ['gps', 'Real GPS', "Moves your pin to where your phone is and follows it. Your browser will ask for permission."],
]

export default function EvacuateControls({ route, trip, mode, onMode, onStart, onStop }) {
  if (trip?.arrived) {
    return (
      <div className="trip-status" role="status">
        <strong>You've arrived at {trip.route.shelter_name}.</strong>
        <button type="button" className="btn-outline" onClick={onStop}>
          Done
        </button>
      </div>
    )
  }

  if (trip) {
    const sim = trip.mode === 'sim'
    const left = 1 - (trip.fraction ?? 0)
    const totalKm = trip.totalKm ?? routeLengthKm(trip.route.geometry?.coordinates)
    const km = totalKm * left
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
        <span className="muted">
          Responders can see your position while you evacuate. Your device:{' '}
          <span className="num">{evacueeId()}</span>
        </span>
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
