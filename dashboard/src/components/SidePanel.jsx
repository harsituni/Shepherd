import { useState } from 'react'

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

const TABS = [
  ['updates', 'Updates'],
  ['reports', 'Reports'],
  ['priority', 'Priority'],
  ['notify', 'Notify'],
]

function NotifyForm() {
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [severity, setSeverity] = useState('advisory')
  const [target, setTarget] = useState('zone')

  return (
    <form className="stack-14" onSubmit={(e) => e.preventDefault()}>
      <label className="field">
        <span>Title</span>
        <input className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="field">
        <span>Message</span>
        <textarea className="textarea" rows="3" value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      <div className="field">
        <span>Severity</span>
        <div className="segmented" role="group" aria-label="Severity">
          {[
            ['advisory', 'Advisory'],
            ['alert', 'Alert'],
            ['evacuation', 'Evacuation'],
          ].map(([v, label]) => (
            <button
              key={v}
              type="button"
              className={v === 'evacuation' ? 'severity-evac' : undefined}
              aria-pressed={severity === v}
              onClick={() => setSeverity(v)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <label className="field">
        <span>Send to</span>
        <select className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="zone">Residents inside hazard zone</option>
          <option value="all">Everyone in Edmonton</option>
        </select>
      </label>
      <button type="submit" className="btn-primary" disabled>
        Send update
      </button>
      <span className="hint">Sending is not connected yet (needs POST /notifications).</span>
      <div className="stack-8">
        <span className="sent-title">Sent</span>
        <p className="empty">Nothing sent yet.</p>
      </div>
    </form>
  )
}

export default function SidePanel({ shelters }) {
  const [tab, setTab] = useState('updates')
  const capacity = shelterCapacityPct(shelters)

  return (
    <aside className="side" aria-label="Status">
      <div className="tiles">
        <Tile label="People at risk" />
        <Tile label="Roads closed" tone="red" />
        <Tile label="Active reroutes" tone="blue" />
        <Tile label="Shelter capacity used" value={capacity == null ? null : `${capacity}%`} />
      </div>

      <div className="tabs" role="tablist" aria-label="Panels">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'updates' && <p className="empty">No rerouting updates yet.</p>}
        {tab === 'reports' && <p className="empty">No reports from phones yet.</p>}
        {tab === 'priority' && <p className="empty">No priority residents loaded yet.</p>}
        {tab === 'notify' && <NotifyForm />}
      </div>
    </aside>
  )
}
