import { useEffect, useId, useRef } from 'react'
import { CloseIcon } from './icons.jsx'

// Centred pop-up on the native <dialog>: showModal() gives the backdrop, focus
// trapping and Esc to close for free. Clicking the backdrop or the X also closes it.
// Children stay mounted while closed, so a half-written update isn't lost.
export default function Dialog({ open, title, onClose, children }) {
  const ref = useRef(null)
  const titleId = useId()

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    else if (!open && d.open) d.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onClose={onClose}
      // The dialog has no padding of its own, so a click whose target is the
      // <dialog> itself landed on the backdrop.
      onClick={(e) => e.target === ref.current && onClose()}
    >
      <div className="dialog-inner">
        <div className="dialog-head">
          <h2 className="section-title" id={titleId}>
            {title}
          </h2>
          <button type="button" className="dialog-close" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="dialog-body">{children}</div>
      </div>
    </dialog>
  )
}
