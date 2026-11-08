import JoinQr from './JoinQr.jsx'

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

// Phone join QR + live numbers. When traffic is on, the tiles show clearance /
// jam metrics from GET /traffic instead of empty placeholders.
export default function SidePanel({ shelters, traffic }) {
  const capacity = shelterCapacityPct(shelters)
  const m = traffic?.metrics
  const compare = traffic?.compare

  return (
    <aside className="side" aria-label="Status">
      <JoinQr />

      {compare?.label && (
        <p className="traffic-side-compare num" role="status">
          {compare.label}
        </p>
      )}

      <div className="tiles">
        <Tile
          label={traffic?.enabled ? 'Cars evacuating' : 'People at risk'}
          value={traffic?.enabled ? (m?.agents_active ?? traffic.active_count) : null}
        />
        <Tile
          label={traffic?.enabled ? 'Jammed roads' : 'Roads closed'}
          value={traffic?.enabled ? m?.jammed_edges : null}
          tone="red"
        />
        <Tile
          label={traffic?.enabled ? 'Traffic reroutes' : 'Active reroutes'}
          value={traffic?.enabled ? m?.reroutes : null}
          tone="blue"
        />
        <Tile
          label={traffic?.enabled ? 'Clearance time' : 'Shelter capacity used'}
          value={
            traffic?.enabled
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
