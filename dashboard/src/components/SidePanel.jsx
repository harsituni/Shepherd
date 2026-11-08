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

// Reports and Notify moved to the left panel (they open as centred pop-ups),
// so this panel is just the phone join QR and the four key numbers.
export default function SidePanel({ shelters }) {
  const capacity = shelterCapacityPct(shelters)

  return (
    <aside className="side" aria-label="Status">
      <JoinQr />

      <div className="tiles">
        <Tile label="People at risk" />
        <Tile label="Roads closed" tone="red" />
        <Tile label="Active reroutes" tone="blue" />
        <Tile label="Shelter capacity used" value={capacity == null ? null : `${capacity}%`} />
      </div>
    </aside>
  )
}
