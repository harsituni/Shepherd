import { useState } from 'react'
import { partsOf, REPORT_KIND_ORDER, REPORT_KINDS } from '../reportKinds.js'
import { CloseIcon, PinIcon } from './icons.jsx'

// Second step of a report: the pin is already dropped on the map, so this sheet
// picks the type and a short message for emergency personnel (30 characters, shown
// to responders on the dashboard, not on the public map). "Move pin" goes back.

const MESSAGE_MAX = 30
// `other` is not in contract v1's report kinds yet (asked Harsit to add it).

function KindIcon({ kind }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`rk rk-${kind}`}
    >
      {partsOf(kind).map(({ d, fill }) => (
        <path key={d} d={d} className={fill ? 'rk-fill' : undefined} />
      ))}
    </svg>
  )
}

export default function ReportSheet({ onSubmit, onClose, onMovePin, sending }) {
  const [kind, setKind] = useState('fire')
  const [note, setNote] = useState('')
  const isOther = kind === 'other'
  // "Other" means nothing to responders without a description, so the message is required.
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
          if (!missingNote) onSubmit({ kind, note: note.trim().slice(0, MESSAGE_MAX) })
        }}
      >
        <div className="sheet-head">
          <h2 id="report-title">Report a hazard</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="report-where">
          <PinIcon className="report-where-icon" />
          <span>At the pin you dropped on the map</span>
          <button type="button" className="link-btn" onClick={onMovePin}>
            Move pin
          </button>
        </div>
        <div className="choice-list" role="radiogroup" aria-label="Type">
          {REPORT_KIND_ORDER.map((v) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={kind === v}
              className="choice choice-icon"
              onClick={() => setKind(v)}
            >
              <KindIcon kind={v} />
              {REPORT_KINDS[v].label}
            </button>
          ))}
        </div>
        <label className="field">
          <span className="field-row">
            <span>{isOther ? 'Message for responders (required)' : 'Message for responders (optional)'}</span>
            <span className={note.length >= MESSAGE_MAX ? 'char-count is-full num' : 'char-count num'} aria-hidden="true">
              {note.length}/{MESSAGE_MAX}
            </span>
          </span>
          <input
            className="text-input"
            value={note}
            maxLength={MESSAGE_MAX}
            required={isOther}
            placeholder={isOther ? 'What did you see?' : 'e.g. Tree across both lanes'}
            enterKeyHint="send"
            onChange={(e) => setNote(e.target.value.slice(0, MESSAGE_MAX))}
          />
        </label>
        <span className="muted small">
          The type and pin show on everyone&apos;s map. Only emergency personnel see your message.
        </span>
        <button type="submit" className="btn-primary" disabled={sending || missingNote}>
          {sending ? 'Sending…' : 'Send report'}
        </button>
      </form>
    </div>
  )
}
