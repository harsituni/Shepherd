const ITEMS = [
  ['Active hazard', 'swatch-hazard'],
  ['Evacuation zone', 'swatch-evac'],
  ['Predicted spread', 'swatch-predicted'],
  ['Closed road', 'swatch-closed'],
  ['Evacuation route', 'swatch-route'],
  ['Shelter', 'swatch-shelter'],
  ['Unsafe shelter', 'swatch-shelter-unsafe'],
  ['Priority resident', 'swatch-priority'],
  ['Evacuee (phone)', 'swatch-evacuee'],
  ['Public report', 'swatch-report'],
]

export default function MapLegend() {
  return (
    <ul className="legend" aria-label="Map legend">
      {ITEMS.map(([label, cls]) => (
        <li key={label}>
          <span className={`swatch ${cls}`} aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  )
}
