import { useCallback, useEffect, useState } from 'react'
import { getNotifications, postNotification } from '../api.js'

const SEVERITY_CLASS = { alert: 'severity-alert', evacuation: 'severity-evac' }

const SEVERITY_LABEL = { advisory: 'Advisory', alert: 'Alert', evacuation: 'Evacuation order' }
const TARGET_LABEL = { zone: 'Hazard zone', all: 'Everyone' }

function sentTime(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

// Lives in the Notify pop-up, which stays mounted while closed (so a draft isn't
// lost); `open` re-fetches the sent list each time the pop-up is opened.
export default function NotifyForm({ open }) {
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
      // keep the list we have; the next send or pop-up open refreshes it
    }
  }, [])

  useEffect(() => {
    if (open) loadSent()
  }, [open, loadSent])

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
