import { useEffect, useRef, useState } from 'react'
import { PauseIcon, PlayIcon, ResetIcon } from './icons.jsx'

// Compass degrees the wind blows FROM (matches wind_from_deg in the contract).
// Labels read start → finish: where the wind comes from, then where it heads.
const WIND_DIRECTIONS = [
  { deg: 270, label: 'West → East' },
  { deg: 315, label: 'Northwest → Southeast' },
  { deg: 0, label: 'North → South' },
  { deg: 45, label: 'Northeast → Southwest' },
  { deg: 90, label: 'East → West' },
  { deg: 135, label: 'Southeast → Northwest' },
  { deg: 180, label: 'South → North' },
  { deg: 225, label: 'Southwest → Northeast' },
]

const HAZARDS = [
  ['wildfire', 'Wildfire'],
  ['tornado', 'Tornado'],
]

function startHint({ canSimulate, idle, startPoint }) {
  if (!canSimulate) return 'Live mode shows real data feeds. Switch to Simulation to run one.'
  if (!idle) return 'Reset to pick a new hazard or start point.'
  if (!startPoint) return 'Click the map to place the start point.'
  return `Start point ${startPoint.lat.toFixed(3)}, ${startPoint.lng.toFixed(3)}. Press play to start.`
}

// The simulation itself runs on the backend (/sim/*). This panel picks the scenario
// and conditions, sends them on play, and drives pause / resume / reset / speed.
// Wind speed and direction apply to both hazards (a tornado travels with the wind);
// relative humidity is wildfire-only.
export default function ControlsPanel({
  canSimulate,
  hazardKind,
  onHazardKindChange,
  sim,
  startPoint,
  onPlay,
  onReset,
  onSpeedChange,
  onWindChange,
  showPredicted,
  onShowPredictedChange,
}) {
  const windTimer = useRef(null)
  useEffect(() => () => clearTimeout(windTimer.current), [])
  const [windKmh, setWindKmh] = useState(18)
  const [windFrom, setWindFrom] = useState(270)
  const [humidity, setHumidity] = useState(22)
  const [speed, setSpeed] = useState(4)
  const [showPriority, setShowPriority] = useState(true)

  const idle = !sim || sim.state === 'idle'
  const running = sim?.state === 'running'
  // Scenario and conditions are sent once on start, so they lock until Reset.
  // Wind speed is the exception: it can change mid-run via POST /sim/wind.
  const locked = !canSimulate || !idle
  const canPlay = canSimulate && (!idle || startPoint != null)
  const currentSpeed = idle ? speed : (sim.speed ?? speed)

  const pickSpeed = (s) => {
    setSpeed(s)
    if (!idle) onSpeedChange(s)
  }

  // While a simulation runs, send the new wind speed once the slider settles.
  const pickWind = (kmh) => {
    setWindKmh(kmh)
    if (idle) return
    clearTimeout(windTimer.current)
    // /sim/wind needs the direction too; it's locked mid-run, so send the one in use.
    windTimer.current = setTimeout(() => onWindChange(kmh, windFrom), 300)
  }

  return (
    <aside className="controls" aria-labelledby="controls-title">
      <h2 className="section-title" id="controls-title">
        Simulate &amp; predict
      </h2>

      <div className="stack-8">
        <span className="field">Hazard</span>
        <div className="choice-grid" role="group" aria-label="Hazard type">
          {HAZARDS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="choice"
              aria-pressed={hazardKind === value}
              disabled={locked}
              onClick={() => onHazardKindChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="hint num">{startHint({ canSimulate, idle, startPoint })}</span>
      </div>

      <fieldset className="stack-14 conditions" disabled={!canSimulate}>
        <legend className="sr-only">Conditions</legend>
        <label className="field">
          <span className="field-row">
            Wind speed <strong className="num">{windKmh} km/h</strong>
          </span>
          <input type="range" min="0" max="60" value={windKmh} onChange={(e) => pickWind(+e.target.value)} />
        </label>
        <label className="field">
          <span>{hazardKind === 'tornado' ? 'Path direction' : 'Wind direction'}</span>
          <select className="select" value={windFrom} disabled={locked} onChange={(e) => setWindFrom(+e.target.value)}>
            {WIND_DIRECTIONS.map((d) => (
              <option key={d.deg} value={d.deg}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        {hazardKind === 'wildfire' && (
          <label className="field">
            <span className="field-row">
              Relative humidity <strong className="num">{humidity}%</strong>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              value={humidity}
              disabled={locked}
              onChange={(e) => setHumidity(+e.target.value)}
            />
          </label>
        )}
      </fieldset>

      <div className="stack-8">
        <div className="playback">
          <button
            type="button"
            className="icon-btn primary"
            aria-label={running ? 'Pause' : idle ? 'Start simulation' : 'Resume'}
            disabled={!canPlay}
            onClick={() => onPlay({ windKmh, windFrom, humidity }, speed)}
          >
            {running ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button type="button" className="icon-btn" aria-label="Reset" disabled={!canSimulate} onClick={onReset}>
            <ResetIcon />
          </button>
          <div className="segmented" role="group" aria-label="Speed">
            {[1, 4, 16].map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={currentSpeed === s}
                disabled={!canSimulate}
                onClick={() => pickSpeed(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
        <span className="elapsed num" aria-live="polite">
          {idle ? 'Not started' : `${sim.state === 'paused' ? 'Paused' : 'Running'} · T+${sim.sim_time ?? 0} min`}
        </span>
      </div>

      <label className="toggle-row">
        <span>Show predicted path</span>
        <input type="checkbox" checked={showPredicted} onChange={(e) => onShowPredictedChange(e.target.checked)} />
      </label>
      <label className="toggle-row">
        <span>Show priority residents</span>
        <input type="checkbox" checked={showPriority} onChange={(e) => setShowPriority(e.target.checked)} />
      </label>
    </aside>
  )
}
