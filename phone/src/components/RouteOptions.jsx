// Route choice cards (issue #55): one card per /route option, showing the shelter,
// ETA · distance · % full, how long the route stays clear and its status. Tapping a
// card picks that route. Blocked routes (the fire is forecast to cut them) and
// routes the forecast can't confirm are greyed out with one short line and can't
// be picked (no "pick anyway" confirm).
import { usable } from '../api.js'

export const STATUS = {
  ok: { label: 'Clear', hint: 'Fire not expected on this route soon' },
  tight: { label: 'Tight', hint: 'Fire is forecast near this route' },
  blocked: { label: 'Blocked', hint: null },
  indeterminate: { label: "Can't confirm", hint: null },
}

function percentFull(shelters, shelterId) {
  const s = shelters?.features?.find((f) => f.id === shelterId)
  if (!s?.properties?.capacity) return null
  return Math.round((s.properties.occupancy / s.properties.capacity) * 100)
}

// Best first, then the other usable routes, then ones we can't confirm, blocked
// last. Within a group the backend's order (its ranking) is kept.
function ordered(options, bestId) {
  const rank = (o) => (o.id === bestId ? 0 : usable(o) ? 1 : o.status === 'indeterminate' ? 2 : 3)
  return [...options].sort((a, b) => rank(a) - rank(b))
}

export function clearLine(o) {
  // Greyed: one short line. The backend's reason (roads, arrival minutes) is too
  // much to read at a glance on a card.
  if (o.status === 'blocked') return 'Fire forecast on this route'
  if (o.status === 'indeterminate') return "The forecast can't confirm this route is safe"
  // No threat: say nothing (the "Clear" status already says it).
  if (o.margin_min == null) return null
  if (o.clear_until_label && !/unknown|no safety guarantee/i.test(o.clear_until_label)) {
    return o.clear_until_label
  }
  return STATUS[o.status]?.hint ?? null
}

function formatKm(km) {
  if (km == null || Number.isNaN(Number(km))) return '–'
  return (Math.round(Number(km) * 10) / 10).toFixed(1)
}

export default function RouteOptions({ options, bestId, chosenId, shelters, onChoose }) {
  return (
    <div className="route-options" role="radiogroup" aria-label="Route options">
      {ordered(options, bestId).map((o) => {
        const greyed = !usable(o)
        const checked = o.id === chosenId
        const full = percentFull(shelters, o.shelter_id)
        const status = STATUS[o.status] ?? STATUS.indeterminate
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-disabled={greyed || undefined}
            className={`route-card status-${o.status}`}
            onClick={() => !greyed && onChoose(o.id)}
          >
            <span className="route-card-top">
              <span className="route-card-name">{o.shelter_name}</span>
              <span className="route-card-status">
                <span className="status-swatch" aria-hidden="true" />
                {status.label}
              </span>
            </span>
            {!greyed && (
              <span className="route-card-trip num">
                <strong>{o.eta_min} min</strong> · {formatKm(o.distance_km)} km
                {full != null && ` · ${full}% full`}
                {o.id === bestId && ' · Recommended'}
              </span>
            )}
            {clearLine(o) && <span className="route-card-clear num">{clearLine(o)}</span>}
          </button>
        )
      })}
    </div>
  )
}
