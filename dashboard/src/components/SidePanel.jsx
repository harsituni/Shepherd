import JoinQr from './JoinQr.jsx'

/** Hide spilled BPR numbers like "Clearance time 297244928 → 15 min". */
function compareLabel(compare) {
  const without = Number(compare?.without_min)
  const withMin = Number(compare?.with_min)
  if (Number.isFinite(without) && Number.isFinite(withMin) && without < 100_000 && withMin < 100_000) {
    return compare.label || `Clearance time ${Math.round(without)} → ${Math.round(withMin)} min`
  }
  if (Number.isFinite(withMin) && withMin < 100_000) {
    return `Clearance time ${Math.round(withMin)} min with anti-gridlock`
  }
  return null
}

function shelterCapacityPct(shelters) {
  const features = shelters?.features ?? []
  const capacity = features.reduce((s, f) => s + (f.properties.capacity ?? 0), 0)
  if (!capacity) return null
  const occupancy = features.reduce((s, f) => s + (f.properties.occupancy ?? 0), 0)
  return Math.round((occupancy / capacity) * 100)
}

function Tile({ label, value, tone }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone ?? ''}`}>{value ?? '—'}</span>
    </div>
  )
}

// Phone join QR + live numbers. Traffic metrics win when Simulate traffic is on;
// otherwise fire-closed roads and phone mid-trip reroutes fill the tiles.
export default function SidePanel({
  shelters,
  traffic,
  closedCount = null,
  phoneReroutes = null,
  peopleAtRisk = null,
}) {
  const capacity = shelterCapacityPct(shelters)
  const m = traffic?.metrics
  const compare = traffic?.compare
  const trafficOn = !!traffic?.enabled

  return (
    <aside className="side" aria-label="Status">
      <JoinQr />

      {compareLabel(compare) && (
        <p className="traffic-side-compare num" role="status">
          {compareLabel(compare)}
        </p>
      )}

      <div className="tiles">
        <Tile
          label={trafficOn ? 'Cars evacuating' : 'People at risk'}
          value={trafficOn ? (m?.agents_active ?? traffic.active_count) : peopleAtRisk}
        />
        <Tile
          label={trafficOn ? 'Jammed roads' : 'Roads closed'}
          value={trafficOn ? m?.jammed_edges : closedCount}
          tone="red"
        />
        <Tile
          label={trafficOn ? 'Traffic reroutes' : 'Active reroutes'}
          value={trafficOn ? m?.reroutes : phoneReroutes}
          tone="blue"
        />
        <Tile
          label={trafficOn ? 'Clearance time' : 'Shelter capacity used'}
          value={
            trafficOn
              ? m?.clearance_min != null
                ? `${Math.round(m.clearance_min)} min`
                : null
              : capacity == null
                ? null
                : `${capacity}%`
          }
        />
      </div>
    </aside>
  )
}
