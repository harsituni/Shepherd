// Route choice cards (issue #55): one card per /route v2 option, showing the
// shelter, ETA · distance · % full, how long the route stays clear and its status.
// Tapping a card picks that route. Blocked routes are greyed out with the API's
// reason and can't be picked (no "pick anyway" confirm): a blocked route is one
// the fire is forecast to cut, so the phone never offers it.

const STATUS = {
  ok: { label: 'Clear', hint: 'Fire not expected on this route soon' },
  tight: { label: 'Tight', hint: 'Fire is forecast near this route' },
  blocked: { label: 'Blocked', hint: null },
}

// The backend's "no fire threat in the forecast" margin (backend/routing/router.py).
const NO_THREAT = 999

function percentFull(shelters, shelterId) {
  const s = shelters?.features?.find((f) => f.id === shelterId)
  if (!s?.properties?.capacity) return null
  return Math.round((s.properties.occupancy / s.properties.capacity) * 100)
}

// Best first, then the other usable routes by spare time, blocked last.
function ordered(options, bestId) {
  const rank = (o) => (o.id === bestId ? 0 : o.status === 'blocked' ? 2 : 1)
  return [...options].sort((a, b) => rank(a) - rank(b) || b.margin_min - a.margin_min || a.eta_min - b.eta_min)
}

function clearLine(o) {
  // Blocked: one short line. The backend's reason (coordinates, arrival minutes) is
  // too much to read at a glance on a card.
  if (o.status === 'blocked') return 'Fire forecast on this route'
  // No threat: say nothing (the "Clear" status already says it). Older backends put a
  // scary "Fire timing unknown…" label when idle; treat that as no threat too.
  if (o.margin_min == null || o.margin_min === NO_THREAT) return null
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
        const blocked = o.status === 'blocked'
        const checked = o.id === chosenId
        const full = percentFull(shelters, o.shelter_id)
        const status = STATUS[o.status] ?? STATUS.tight
        return (
          <button
            key={o.shelter_id}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-disabled={blocked || undefined}
            className={`route-card status-${o.status}`}
            onClick={() => !blocked && onChoose(o.shelter_id)}
          >
            <span className="route-card-top">
              <span className="route-card-name">{o.shelter_name}</span>
              <span className="route-card-status">
                <span className="status-swatch" aria-hidden="true" />
                {status.label}
              </span>
            </span>
            {!blocked && (
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
