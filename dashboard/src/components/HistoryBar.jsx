// Timeline slider: T+0 → now (recorded snapshots) → now + forecast horizon.
// Dragging redraws the hazard at that minute and pauses the sim (App does both);
// "Back to live" returns to following the current step.
export default function HistoryBar({ now, horizon = 0, viewing, onScrub, onLive }) {
  const disabled = now == null
  const live = now ?? 0
  const max = live + horizon
  const value = Math.min(viewing ?? live, max)
  const pct = (t) => (max > 0 ? (t / max) * 100 : 0)

  const ticks = [{ t: 0, label: 'T+0' }]
  if (live > 0) ticks.push({ t: live, label: 'Now', now: true })
  if (horizon > 0) ticks.push({ t: max, label: `T+${max}` })

  let status = 'live'
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
          {ticks.map(({ t, label, now: isNow }) => (
            <span
              key={label}
              className={isNow ? 'history-tick is-now' : 'history-tick'}
              style={{ left: `${pct(t)}%` }}
            >
              {label}
            </span>
          ))}
        </span>
      </label>
      <span className="history-viewing num">
        Viewing <strong>{disabled ? 'not started' : status}</strong>
      </span>
      <button type="button" className="btn-outline" disabled={viewing == null} onClick={onLive}>
        Back to live
      </button>
    </div>
  )
}
