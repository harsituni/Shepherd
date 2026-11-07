import { useState } from 'react'

// Step 0: scrubbing only moves the slider. Redrawing past states needs
// history snapshots (not in the contract yet).
export default function HistoryBar({ simTime }) {
  const now = simTime ?? 0
  const [viewing, setViewing] = useState(null) // null = following live
  const value = viewing ?? now
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(now * f))

  return (
    <div className="history">
      <span className="history-label">History</span>
      <label className="history-track">
        <span className="sr-only">Scrub disaster progression</span>
        <input
          type="range"
          min="0"
          max={now}
          value={Math.min(value, now)}
          onChange={(e) => setViewing(+e.target.value)}
          disabled={simTime == null}
        />
        <span className="history-ticks num">
          {ticks.map((t, i) => (
            <span key={i}>
              T+{t}
              {i === ticks.length - 1 ? ' now' : ''}
            </span>
          ))}
        </span>
      </label>
      <span className="history-viewing num">
        Viewing <strong>{viewing == null ? 'live' : `T+${value} min`}</strong>
      </span>
      <button type="button" className="btn-outline" disabled={viewing == null} onClick={() => setViewing(null)}>
        Back to live
      </button>
    </div>
  )
}
