import { useState } from 'react'
import { CloseIcon } from './icons.jsx'

// "Priority" rail button: people with a disability register an Alberta disability
// ID so responders see them as a priority resident on the dashboard map. Only the
// ID type and the last 4 characters of the number are sent, never the full number.

export const ID_TYPES = [
  ['dats', 'DATS (Edmonton)'],
  ['parking_placard', 'Parking placard'],
  ['aish', 'AISH card'],
  ['adap', 'ADAP client ID'],
  ['pdd', 'PDD program'],
  ['cnib', 'CNIB card'],
  ['other', 'Other ID'],
]

export const NEEDS = [
  ['mobility', 'Wheelchair or mobility aid'],
  ['no_vehicle', 'No vehicle'],
  ['vision', 'Blind or low vision'],
  ['hearing', 'Deaf or hard of hearing'],
  ['medical', 'Medical equipment or oxygen'],
  ['cognitive', 'Cognitive or developmental'],
  ['other', 'Other'],
]

const label = (list, v) => list.find(([k]) => k === v)?.[1] ?? v
const cleanId = (s) => s.replace(/[^0-9a-z]/gi, '')

// registered: null | { id_type, needs, note }
export default function PrioritySheet({ registered, sending, onSubmit, onRemove, onClose }) {
  const [idType, setIdType] = useState(registered?.id_type ?? 'dats')
  const [idNumber, setIdNumber] = useState('')
  const [needs, setNeeds] = useState(registered?.needs ?? [])
  const [note, setNote] = useState(registered?.note ?? '')
  const [editing, setEditing] = useState(!registered)

  const digits = cleanId(idNumber)
  const idOk = digits.length >= 4
  const canSubmit = idOk && needs.length > 0 && !sending
  const toggleNeed = (v) => setNeeds((cur) => (cur.includes(v) ? cur.filter((n) => n !== v) : [...cur, v]))

  return (
    <div className="sheet-scrim" onClick={onClose}>
      <form
        className="sheet priority-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="priority-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSubmit) return
          onSubmit({ id_type: idType, id_last4: digits.slice(-4).toUpperCase(), needs, note: note.trim() })
        }}
      >
        <div className="sheet-head">
          <h2 id="priority-title">Priority resident</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        {!editing ? (
          <>
            <div className="priority-status" role="status">
              <strong>You&apos;re registered as a priority resident.</strong>
              <span>
                {label(ID_TYPES, registered.id_type)} · {registered.needs.map((n) => label(NEEDS, n)).join(', ')}
              </span>
              <span className="muted small">Responders see this on their map while your location is shared.</span>
            </div>
            <button type="button" className="btn-primary" onClick={() => setEditing(true)}>
              Update details
            </button>
            <button type="button" className="btn-outline" disabled={sending} onClick={onRemove}>
              {sending ? 'Removing…' : 'Remove priority status'}
            </button>
          </>
        ) : (
          <>
            <p className="muted small priority-intro">
              If you have a disability, register an Alberta disability ID so responders know you may need extra help
              to evacuate.
            </p>
            <div className="field">
              <span>ID type</span>
              <div className="choice-list" role="radiogroup" aria-label="ID type">
                {ID_TYPES.map(([v, text]) => (
                  <button
                    key={v}
                    type="button"
                    role="radio"
                    aria-checked={idType === v}
                    className="choice"
                    onClick={() => setIdType(v)}
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
            <label className="field">
              <span>ID number</span>
              <input
                className="text-input"
                value={idNumber}
                inputMode="text"
                autoComplete="off"
                maxLength={30}
                onChange={(e) => setIdNumber(e.target.value)}
              />
              <span className="small">
                {idNumber && !idOk
                  ? 'Enter at least 4 letters or digits.'
                  : 'Only the last 4 characters are shared with responders.'}
              </span>
            </label>
            <div className="field">
              <span>What help might you need?</span>
              <div className="choice-list" role="group" aria-label="Needs">
                {NEEDS.map(([v, text]) => (
                  <button
                    key={v}
                    type="button"
                    role="checkbox"
                    aria-checked={needs.includes(v)}
                    className="choice"
                    onClick={() => toggleNeed(v)}
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
            <label className="field">
              <span>Note for responders (optional)</span>
              <textarea rows="2" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="submit" className="btn-primary" disabled={!canSubmit}>
              {sending ? 'Sending…' : registered ? 'Save details' : 'Register as priority'}
            </button>
          </>
        )}
      </form>
    </div>
  )
}
