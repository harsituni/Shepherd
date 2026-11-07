import { useState } from 'react'
import { PauseIcon, PlayIcon, ResetIcon } from './icons.jsx'

// Compass degrees the wind blows FROM (matches wind_from_deg in the contract).
const WIND_DIRECTIONS = [
  { deg: 270, label: 'From west (→ east)' },
  { deg: 315, label: 'From northwest (→ southeast)' },
  { deg: 0, label: 'From north (→ south)' },
  { deg: 45, label: 'From northeast (→ southwest)' },
  { deg: 90, label: 'From east (→ west)' },
  { deg: 135, label: 'From southeast (→ northwest)' },
  { deg: 180, label: 'From south (→ north)' },
  { deg: 225, label: 'From southwest (→ northeast)' },
]

function dryness(pct) {
  if (pct < 34) return 'Low'
  if (pct < 67) return 'Medium'
  return 'High'
}

// Step 0: only the hazard type is used (it sets `kind` for map-click POST /hazards).
// The other controls hold local state until /sim/* is wired in Step 2.
export default function ControlsPanel({ hazardKind, onHazardKindChange }) {
  const [windKmh, setWindKmh] = useState(18)
  const [windFrom, setWindFrom] = useState(270)
  const [fuel, setFuel] = useState(75)
  const [humidity, setHumidity] = useState(22)
  const [riverRise, setRiverRise] = useState(0.5)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(4)
  const [showPredicted, setShowPredicted] = useState(true)
  const [showPriority, setShowPriority] = useState(true)

  return (
    <aside className="controls" aria-labelledby="controls-title">
      <h2 className="section-title" id="controls-title">
        Simulate &amp; predict
      </h2>

      <div className="stack-8">
        <span className="field">Hazard</span>
        <div className="choice-grid" role="group" aria-label="Hazard type">
          {[
            ['wildfire', 'Wildfire'],
            ['flood', 'Flood'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="choice"
              aria-pressed={hazardKind === value}
              onClick={() => onHazardKindChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="hint">Click the map to place the start point.</span>
      </div>

      {hazardKind === 'wildfire' ? (
        <div className="stack-14">
          <label className="field">
            <span className="field-row">
              Wind speed <strong className="num">{windKmh} km/h</strong>
            </span>
            <input type="range" min="0" max="60" value={windKmh} onChange={(e) => setWindKmh(+e.target.value)} />
          </label>
          <label className="field">
            <span>Wind direction</span>
            <select className="select" value={windFrom} onChange={(e) => setWindFrom(+e.target.value)}>
              {WIND_DIRECTIONS.map((d) => (
                <option key={d.deg} value={d.deg}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-row">
              Fuel dryness <strong>{dryness(fuel)}</strong>
            </span>
            <input type="range" min="0" max="100" value={fuel} onChange={(e) => setFuel(+e.target.value)} />
          </label>
          <label className="field">
            <span className="field-row">
              Relative humidity <strong className="num">{humidity}%</strong>
            </span>
            <input type="range" min="0" max="100" value={humidity} onChange={(e) => setHumidity(+e.target.value)} />
          </label>
        </div>
      ) : (
        <div className="stack-14">
          <label className="field">
            <span className="field-row">
              River rise rate <strong className="num">{riverRise.toFixed(1)} m/hr</strong>
            </span>
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={riverRise}
              onChange={(e) => setRiverRise(+e.target.value)}
            />
          </label>
        </div>
      )}

      <div className="playback">
        <button
          type="button"
          className="icon-btn primary"
          aria-label={playing ? 'Pause' : 'Play'}
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button type="button" className="icon-btn" aria-label="Reset">
          <ResetIcon />
        </button>
        <div className="segmented" role="group" aria-label="Speed">
          {[1, 4, 16].map((s) => (
            <button key={s} type="button" aria-pressed={speed === s} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
      </div>

      <label className="toggle-row">
        <span>Show predicted path</span>
        <input type="checkbox" checked={showPredicted} onChange={(e) => setShowPredicted(e.target.checked)} />
      </label>
      <label className="toggle-row">
        <span>Show priority residents</span>
        <input type="checkbox" checked={showPriority} onChange={(e) => setShowPriority(e.target.checked)} />
      </label>
    </aside>
  )
}
