import { hazardSentence as hazardLine, isCurrentCore, nearestHazard } from '../geo.js'
import { InfoIcon, WarningIcon } from './icons.jsx'
import { mostSevere, SEVERITY } from './Notifications.jsx'

const KIND_LABEL = { wildfire: 'Wildfire', tornado: 'Tornado' }
// Tornado simulation is a beta feature; its alerts say so.
const BETA = ' (beta)'

function kindTitle(near, features) {
  if (near?.kind === 'tornado') {
    const ef = near.feature?.properties?.ef_label
    return ef ? `${ef} tornado` : 'Tornado'
  }
  const kinds = [...new Set(features.map((f) => f.properties.kind))]
  return kinds.map((k) => KIND_LABEL[k] ?? k).join(' / ')
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

  const title = kindTitle(near, features)
  const core = features.find((f) => f.properties?.kind === 'tornado')
  const efBits = core?.properties
  const tornadoStats =
    efBits?.ef_label &&
    `${efBits.ef_label} · ${efBits.wind_est_kmh ?? '—'} km/h · ${efBits.path_width_m ?? '—'} m wide`

  if (!location) {
    return (
      <Banner
        tone="advisory"
        Icon={InfoIcon}
        title={`Active ${title.toLowerCase()} in the Edmonton area${core ? BETA : ''}`}
        line={tornadoStats || 'Tap the map to set your location and get a safe route.'}
      />
    )
  }

  if (near?.inside) {
    return (
      <Banner
        tone="danger"
        Icon={WarningIcon}
        title={`You are inside the ${title.toLowerCase()} path${core ? BETA : ''}`}
        line="Leave now. Follow the route below."
        assertive
      />
    )
  }

  return <Banner tone="alert" Icon={WarningIcon} title={`${title} nearby${core ? BETA : ''}`} line={hazardLine(near)} />
}
