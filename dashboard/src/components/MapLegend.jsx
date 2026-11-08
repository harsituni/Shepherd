import { useState } from 'react'
import { MinusIcon, PlusIcon } from './icons.jsx'

const ITEMS = [
  ['Active hazard', 'swatch-hazard'],
  ['Evacuation zone', 'swatch-evac'],
  ['Predicted spread', 'swatch-predicted'],
  ['Traffic free', 'swatch-traffic-free'],
  ['Traffic busy', 'swatch-traffic-busy'],
  ['Traffic jammed', 'swatch-traffic-jammed'],
  ['Traffic gridlock', 'swatch-traffic-gridlock'],
  ['Closed road', 'swatch-closed'],
  ['Evacuation route', 'swatch-route'],
  ['Shelter', 'swatch-shelter'],
  ['Unsafe shelter', 'swatch-shelter-unsafe'],
  ['Priority resident', 'swatch-priority'],
  ['Evacuee (phone)', 'swatch-evacuee'],
  ['Public report', 'swatch-report'],
]

// Floating map legend, bottom-left. A slim blue "LEGEND" header with a minimise
// button; minimised, the list folds down into the header (CSS height transition),
// leaving just the header docked at the bottom of the map with a plus to expand.
export default function MapLegend() {
  const [open, setOpen] = useState(true)
  return (
    <section className={open ? 'legend' : 'legend is-collapsed'} aria-labelledby="legend-title">
      <div className="legend-head">
        {/* Written "Legend" and shown in capitals by CSS, so screen readers say the word. */}
        <h2 className="legend-title" id="legend-title">
          Legend
        </h2>
        <button
          type="button"
          className="legend-toggle"
          aria-expanded={open}
          aria-controls="legend-items"
          aria-label={open ? 'Minimise legend' : 'Expand legend'}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <MinusIcon /> : <PlusIcon />}
        </button>
      </div>
      {/* Always rendered so it can animate; `inert` keeps it out of focus and
          screen readers while folded away. */}
      <div className="legend-body" inert={!open}>
        <ul className="legend-items" id="legend-items">
          {ITEMS.map(([label, cls]) => (
            <li key={label}>
              <span className={`swatch ${cls}`} aria-hidden="true" />
              {label}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
