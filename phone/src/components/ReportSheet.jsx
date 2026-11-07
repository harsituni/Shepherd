import { useState } from 'react'
import { CloseIcon } from './icons.jsx'

// `other` is not in contract v1's report kinds yet (asked Harsit to add it).
const KINDS = [
  ['fire', 'Fire'],
  ['flooded_road', 'Flooded road'],
  ['blocked_road', 'Blocked road'],
  ['other', 'Other'],
]

export default function ReportSheet({ onSubmit, onClose, sending }) {
  const [kind, setKind] = useState('fire')
  const [note, setNote] = useState('')
  const isOther = kind === 'other'
  // "Other" means nothing to responders without a description, so the note is required.
  const missingNote = isOther && note.trim() === ''

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
          if (!missingNote) onSubmit({ kind, note: note.trim() })
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
          <span>{isOther ? 'What did you see? (required)' : 'Note (optional)'}</span>
          <textarea
            rows="2"
            value={note}
            maxLength={200}
            required={isOther}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <span className="muted small">Uses your current location on the map.</span>
        <button type="submit" className="btn-primary" disabled={sending || missingNote}>
          {sending ? 'Sending…' : 'Send report'}
        </button>
      </form>
    </div>
  )
}
