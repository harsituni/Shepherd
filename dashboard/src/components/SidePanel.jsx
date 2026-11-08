import { useCallback, useEffect, useState } from 'react'
import { getNotifications, postNotification } from '../api.js'
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

const REPORT_KINDS = {
  fire: 'Fire',
  flooded_road: 'Flooded road',
  blocked_road: 'Blocked road',
  safe: "I'm safe",
  sos: 'SOS',
  other: 'Other',
}

// Newest first: highest sim_time, then highest id number as a tie-break.
function sortedReports(reports) {
  const idNum = (f) => Number(String(f.id ?? '').replace(/\D/g, '')) || 0
  return [...(reports?.features ?? [])].sort(
    (a, b) => (b.properties?.sim_time ?? 0) - (a.properties?.sim_time ?? 0) || idNum(b) - idNum(a),
  )
}

function ReportsList({ reports, onSelect }) {
  const items = sortedReports(reports)
  if (items.length === 0) return <p className="empty">No reports from phones yet.</p>
  return (
    <ul className="report-list">
      {items.map((f) => {
        const { kind, note, sim_time: t } = f.properties ?? {}
        const [lon, lat] = f.geometry.coordinates
        return (
          <li key={f.id}>
            <button type="button" className="report-item" onClick={() => onSelect(f)}>
              <span className="report-row">
                <strong className={kind === 'sos' ? 'report-kind sos' : 'report-kind'}>
                  {REPORT_KINDS[kind] ?? kind}
                </strong>
                <span className="num report-time">{t == null ? '' : `T+${t}`}</span>
              </span>
              {note && <span className="report-note">{note}</span>}
              <span className="num report-loc">
                {lat.toFixed(3)}, {lon.toFixed(3)}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

const TABS = [
  ['reports', 'Reports'],
  ['notify', 'Notify'],
]

const SEVERITY_CLASS = { alert: 'severity-alert', evacuation: 'severity-evac' }

const SEVERITY_LABEL = { advisory: 'Advisory', alert: 'Alert', evacuation: 'Evacuation order' }
const TARGET_LABEL = { zone: 'Hazard zone', all: 'Everyone' }

function sentTime(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function NotifyForm() {
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [severity, setSeverity] = useState('advisory')
  const [target, setTarget] = useState('zone')
  const [sent, setSent] = useState([])
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState(null) // { text, error }

  const loadSent = useCallback(async () => {
    try {
      setSent(await getNotifications())
    } catch {
      // keep the list we have; the next send or tab open refreshes it
    }
  }, [])

  useEffect(() => {
    loadSent()
  }, [loadSent])

  const canSend = title.trim() !== '' && message.trim() !== '' && !sending

  const onSubmit = async (e) => {
    e.preventDefault()
    if (!canSend) return
    setSending(true)
    setStatus(null)
    try {
      await postNotification({ title: title.trim(), message: message.trim(), severity, target })
      setTitle('')
      setMessage('')
      setStatus({ text: 'Sent. Phones show it within a few seconds.' })
      await loadSent()
    } catch (err) {
      setStatus({ text: `Couldn't send: ${err.message}`, error: true })
    } finally {
      setSending(false)
    }
  }

  return (
    <form className="stack-14" onSubmit={onSubmit}>
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
              className={SEVERITY_CLASS[v]}
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
      <button type="submit" className="btn-primary" disabled={!canSend}>
        {sending ? 'Sending…' : 'Send update'}
      </button>
      {status && (
        <span className={status.error ? 'hint sim-error' : 'hint'} role="status">
          {status.text}
        </span>
      )}
      <div className="stack-8">
        <span className="sent-title">Sent</span>
        {sent.length === 0 ? (
          <p className="empty">Nothing sent yet.</p>
        ) : (
          <ul className="report-list">
            {sent.map((n) => (
              <li key={n.id} className="sent-item">
                <span className="report-row">
                  <strong className="report-kind">{n.title}</strong>
                  <span className="num report-time">{sentTime(n.time)}</span>
                </span>
                <span className="report-note">{n.message}</span>
                <span className="report-loc">
                  <span className={`sent-${n.severity}`}>{SEVERITY_LABEL[n.severity] ?? n.severity}</span> ·{' '}
                  {TARGET_LABEL[n.target] ?? 'Everyone'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </form>
  )
}

export default function SidePanel({ shelters, reports, onReportSelect }) {
  const [tab, setTab] = useState('reports')
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
        {tab === 'reports' && <ReportsList reports={reports} onSelect={onReportSelect} />}
        {tab === 'notify' && <NotifyForm />}
      </div>
    </aside>
  )
}
