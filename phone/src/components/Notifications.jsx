import { useState } from 'react'
import { CloseIcon, InfoIcon, WarningIcon } from './icons.jsx'

// Severity → label, icon and colour class (Advisory blue, Alert deep yellow, Evacuation order deep red).
export const SEVERITY = {
  advisory: { label: 'Advisory', rank: 1, Icon: InfoIcon },
  alert: { label: 'Alert', rank: 2, Icon: WarningIcon },
  evacuation: { label: 'Evacuation order', rank: 3, Icon: WarningIcon },
}
const sev = (n) => SEVERITY[n?.severity] ?? SEVERITY.advisory
const sevKey = (n) => (SEVERITY[n?.severity] ? n.severity : 'advisory')

const timeOf = (n) => {
  const t = Date.parse(n?.time)
  return Number.isNaN(t) ? 0 : t
}

function formatTime(value) {
  const t = Date.parse(value)
  if (Number.isNaN(t)) return value ?? ''
  return new Date(t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const newestFirst = (list) => [...(list ?? [])].sort((a, b) => timeOf(b) - timeOf(a))

// The one the persistent banner shows: most severe, then newest.
export function mostSevere(list) {
  return [...(list ?? [])].sort((a, b) => sev(b).rank - sev(a).rank || timeOf(b) - timeOf(a))[0] ?? null
}

function Meta({ n }) {
  const { label } = sev(n)
  const time = formatTime(n.time)
  return (
    <span className="note-meta num">
      {label}
      {time && ` · ${time}`}
    </span>
  )
}

// Slides down over the header when a new government update arrives.
// Tap to show the full message; the close button dismisses it.
export function NotificationPopup({ notification, onDismiss }) {
  const [expanded, setExpanded] = useState(false)
  const { Icon } = sev(notification)
  return (
    <div className={`popup sev-${sevKey(notification)}`} role="alert">
      <Icon className="popup-icon" />
      <button
        type="button"
        className="popup-body"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        <Meta n={notification} />
        <strong className="popup-title">{notification.title}</strong>
        {expanded ? (
          <span className="popup-message">{notification.message}</span>
        ) : (
          <span className="popup-more">Tap to read</span>
        )}
      </button>
      <button type="button" className="icon-btn" aria-label="Dismiss" onClick={onDismiss}>
        <CloseIcon />
      </button>
    </div>
  )
}

export function AlertsTab({ notifications }) {
  const items = newestFirst(notifications)
  if (items.length === 0) {
    return (
      <div className="gov">
        <p className="muted">No official alerts yet. Alerts from emergency officials will appear here.</p>
      </div>
    )
  }
  return (
    <div className="gov">
      <ul className="list">
        {items.map((n) => (
          <li key={n.id} className={`sev-${sevKey(n)}`}>
            <Meta n={n} />
            <strong>{n.title}</strong>
            <span>{n.message}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
