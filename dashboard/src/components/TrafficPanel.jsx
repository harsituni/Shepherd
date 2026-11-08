import { useEffect, useState } from 'react'

function Metric({ label, value }) {
  return (
    <div className="traffic-metric">
      <span className="traffic-metric-label">{label}</span>
      <strong className="num">{value ?? '—'}</strong>
    </div>
  )
}

/** Guard against a spilled BPR ETA (e.g. "297244928 → 15 min"). */
function formatCompareLabel(compare) {
  const without = Number(compare?.without_min)
  const withMin = Number(compare?.with_min)
  if (Number.isFinite(without) && Number.isFinite(withMin) && without < 100_000 && withMin < 100_000) {
    return compare.label || `Clearance time ${Math.round(without)} → ${Math.round(withMin)} min`
  }
  if (Number.isFinite(withMin) && withMin < 100_000) {
    return `Clearance time ${Math.round(withMin)} min with anti-gridlock`
  }
  return compare?.label && !/\d{6,}/.test(compare.label) ? compare.label : null
}

// Left-panel traffic controls (contract v2.1): on/off, crowd size, anti-gridlock,
// metrics, and Compare (naive pile-up vs spread-out clearance).
export default function TrafficPanel({ traffic, canSimulate, busy, onConfig, onCompare }) {
  const enabled = !!traffic?.enabled
  const anti = traffic?.anti_gridlock !== false
  const count = traffic?.simulated_count ?? 2000
  const [slider, setSlider] = useState(count)
  const metrics = traffic?.metrics ?? {}
  const compare = traffic?.compare

  useEffect(() => {
    setSlider(count)
  }, [count])

  return (
    <section className="traffic-panel" aria-labelledby="traffic-title">
      <h2 className="section-title" id="traffic-title">
        Traffic
      </h2>
      <p className="hint">
        Thousands of cars + judge phones jam roads. Anti-gridlock spreads them and
        phones get mid-trip reroutes.
      </p>

      <label className="toggle-row">
        <span>Simulate traffic</span>
        <input
          type="checkbox"
          checked={enabled}
          disabled={!canSimulate || busy}
          onChange={(e) => onConfig({ enabled: e.target.checked, simulated_count: slider })}
        />
      </label>

      <label className="field">
        <span className="field-row">
          Evacuating cars <strong className="num">{slider.toLocaleString()}</strong>
        </span>
        <input
          type="range"
          min="0"
          max="5000"
          step="100"
          value={slider}
          disabled={!canSimulate || busy}
          onChange={(e) => setSlider(+e.target.value)}
          onMouseUp={() => onConfig({ simulated_count: slider, enabled: true })}
          onTouchEnd={() => onConfig({ simulated_count: slider, enabled: true })}
        />
      </label>

      <label className="toggle-row">
        <span>Anti-gridlock</span>
        <input
          type="checkbox"
          checked={anti}
          disabled={!canSimulate || busy || !enabled}
          onChange={(e) => onConfig({ anti_gridlock: e.target.checked, enabled: true })}
        />
      </label>

      <div className="traffic-metrics num" aria-live="polite">
        <Metric
          label="Clearance"
          value={metrics.clearance_min != null ? `${Math.round(metrics.clearance_min)} min` : null}
        />
        <Metric
          label="Avg ETA"
          value={metrics.avg_eta_min != null ? `${Math.round(metrics.avg_eta_min)} min` : null}
        />
        <Metric label="Jammed roads" value={metrics.jammed_edges} />
        <Metric label="Reroutes" value={metrics.reroutes} />
        <Metric label="Cars on roads" value={metrics.agents_active ?? traffic?.active_count} />
        <Metric
          label="Peak load"
          value={
            metrics.max_vc != null
              ? `${Math.min(500, Math.round(metrics.max_vc * 100))}%`
              : null
          }
        />
      </div>

      {compare?.label && (
        <p className="traffic-compare-label num" role="status">
          {formatCompareLabel(compare)}
        </p>
      )}

      <button
        type="button"
        className="btn-outline traffic-compare-btn"
        disabled={!canSimulate || busy || !enabled}
        onClick={onCompare}
      >
        {busy ? 'Comparing…' : 'Compare'}
      </button>
      <p className="hint">Runs without anti-gridlock, then with it — shows clearance time saved.</p>
    </section>
  )
}
