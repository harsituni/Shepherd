import { useState } from 'react'
import { CloseIcon } from './icons.jsx'

const KINDS = [
  ['fire', 'Fire'],
  ['flooded_road', 'Flooded road'],
  ['blocked_road', 'Blocked road'],
]

export default function ReportSheet({ onSubmit, onClose, sending }) {
  const [kind, setKind] = useState('fire')
  const [note, setNote] = useState('')

  return (
    <div className="sheet-scrim" onClick={onClose}>
      <form
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit({ kind, note: note.trim() })
        }}
      >
        <div className="sheet-head">
          <h2 id="report-title">Report a hazard</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="choice-list" role="radiogroup" aria-label="Type">
          {KINDS.map(([v, label]) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={kind === v}
              className="choice"
              onClick={() => setKind(v)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Note (optional)</span>
          <textarea rows="2" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        </label>
        <span className="muted small">Uses your current location on the map.</span>
        <button type="submit" className="btn-primary" disabled={sending}>
          {sending ? 'Sending…' : 'Send report'}
        </button>
      </form>
    </div>
  )
}
