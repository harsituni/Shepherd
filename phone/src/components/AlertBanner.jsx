import { isCurrentCore, nearestHazard } from '../geo.js'
import { InfoIcon, WarningIcon } from './icons.jsx'
import { mostSevere, SEVERITY } from './Notifications.jsx'

const KIND_LABEL = { wildfire: 'Wildfire', flood: 'Flood' }
const KIND_NOUN = { wildfire: 'Fire', flood: 'Flooding' }

// "Fire is 2.4 km west of you, moving east." from /hazards + the user's location.
function hazardLine(near) {
  if (!near) return null
  const noun = KIND_NOUN[near.kind] ?? 'Hazard'
  if (near.inside) return `You are inside the ${(KIND_LABEL[near.kind] ?? 'hazard').toLowerCase()} zone. Leave now.`
  const moving = near.moving ? `, moving ${near.moving}` : ''
  return `${noun} is ${near.km.toFixed(1)} km ${near.direction} of you${moving}.`
}

function Banner({ tone, Icon, title, line, assertive }) {
  return (
    <div className={`alert alert-${tone}`} role={assertive ? 'alert' : 'status'}>
      <Icon className="alert-icon" />
      <div className="alert-text">
        <strong>{title}</strong>
        {line && <span className="num">{line}</span>}
      </div>
    </div>
  )
}

// The persistent banner under the header. A government notification wins (the most
// severe active one); otherwise it's built from /hazards and the user's location.
export default function AlertBanner({ hazards, location, notifications }) {
  const near = location ? nearestHazard(location, hazards) : null
  const top = mostSevere(notifications)

  if (top) {
    const severity = SEVERITY[top.severity] ? top.severity : 'advisory'
    const tone = severity === 'evacuation' || near?.inside ? 'danger' : severity
    return (
      <Banner
        tone={tone}
        Icon={SEVERITY[severity].Icon}
        title={top.title}
        line={hazardLine(near) ?? top.message}
        assertive={tone === 'danger'}
      />
    )
  }

  const features = (hazards?.features ?? []).filter(isCurrentCore)
  if (features.length === 0) {
    return <Banner tone="advisory" Icon={InfoIcon} title="No active hazards" line="We'll alert you here if anything changes." />
  }

  const kinds = [...new Set(features.map((f) => f.properties.kind))]
  const title = kinds.map((k) => KIND_LABEL[k] ?? k).join(' and ')

  if (!location) {
    return (
      <Banner
        tone="advisory"
        Icon={InfoIcon}
        title={`Active ${title.toLowerCase()} in the Edmonton area`}
        line="Tap the map to set your location and get a safe route."
      />
    )
  }

  if (near?.inside) {
    return (
      <Banner
        tone="danger"
        Icon={WarningIcon}
        title={`You are inside the ${(KIND_LABEL[near.kind] ?? 'hazard').toLowerCase()} zone`}
        line="Leave now. Follow the route below."
        assertive
      />
    )
  }

  return <Banner tone="alert" Icon={WarningIcon} title={`${title} nearby`} line={hazardLine(near)} />
}
