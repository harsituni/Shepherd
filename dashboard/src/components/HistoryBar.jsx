// Timeline slider: T+0 → now (recorded snapshots) → now + forecast horizon.
// Dragging redraws the hazard at that minute and pauses the sim (App does both);
// "Back to live" (shown only while scrubbed away) returns to the current step.
export default function HistoryBar({ now, horizon = 0, viewing, onScrub, onLive }) {
  const disabled = now == null
  const live = now ?? 0
  const max = live + horizon
  const value = Math.min(viewing ?? live, max)
  const pct = (t) => (max > 0 ? (t / max) * 100 : 0)

  // Only the forecast end is labelled. No "Now" tick (the thumb already shows the
  // current position) and no "T+0" (the slider's left end is T+0).
  const ticks = []
  if (horizon > 0) ticks.push({ t: max, label: `T+${max}` })
  // Centre each label on its spot, but keep it inside the bar near either end.
  const shift = (p) => (p < 8 ? '0' : p > 92 ? '-100%' : '-50%')

  let status = 'Live'
  if (viewing != null) status = `T+${value} min${value > live ? ' (forecast)' : ''}`

  return (
    <div className="history">
      <span className="history-label">History</span>
      <label className="history-track">
        <span className="sr-only">Scrub disaster progression, past and forecast</span>
        <input
          type="range"
          min="0"
          max={max}
          value={value}
          onChange={(e) => onScrub(+e.target.value)}
          disabled={disabled || max === 0}
          aria-valuetext={`T+${value} minutes${value > live ? ', forecast' : ''}`}
        />
        <span className="history-ticks num" aria-hidden="true">
          {ticks.map(({ t, label }) => (
            <span
              key={label}
              className="history-tick"
              style={{ left: `${pct(t)}%`, transform: `translateX(${shift(pct(t))})` }}
            >
              {label}
            </span>
          ))}
        </span>
      </label>
      <span className="history-viewing num">
        Viewing <strong>{disabled ? 'not started' : status}</strong>
      </span>
      {/* Only while scrubbed away from live; following live there's nothing to go back to. */}
      {viewing != null && (
        <button type="button" className="btn-outline" onClick={onLive}>
          Back to live
        </button>
      )}
    </div>
  )
}
