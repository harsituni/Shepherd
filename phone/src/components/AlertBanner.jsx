import { nearestHazard } from '../geo.js'
import { InfoIcon, WarningIcon } from './icons.jsx'

const KIND_LABEL = { wildfire: 'Wildfire', flood: 'Flood' }
const KIND_NOUN = { wildfire: 'Fire', flood: 'Flooding' }

// Built only from /hazards and the user's location (distance/direction computed
// client-side). Government notifications will drive this once /notifications exists.
export default function AlertBanner({ hazards, location }) {
  const features = (hazards?.features ?? []).filter((f) => f.properties?.zone === 'core')

  if (features.length === 0) {
    return (
      <div className="alert alert-calm" role="status">
        <InfoIcon className="alert-icon" />
        <div className="alert-text">
          <strong>No active hazards</strong>
          <span>We'll alert you here if anything changes.</span>
        </div>
      </div>
    )
  }

  const kinds = [...new Set(features.map((f) => f.properties.kind))]
  const title = kinds.map((k) => KIND_LABEL[k] ?? k).join(' and ')

  if (!location) {
    return (
      <div className="alert alert-calm" role="status">
        <InfoIcon className="alert-icon" />
        <div className="alert-text">
          <strong>Active {title.toLowerCase()} in the Edmonton area</strong>
          <span>Tap the map to set your location and get a safe route.</span>
        </div>
      </div>
    )
  }

  const near = nearestHazard(location, hazards)
  const noun = KIND_NOUN[near?.kind] ?? 'Hazard'

  if (near?.inside) {
    return (
      <div className="alert alert-danger" role="alert">
        <WarningIcon className="alert-icon" />
        <div className="alert-text">
          <strong>You are inside the {(KIND_LABEL[near.kind] ?? 'hazard').toLowerCase()} zone</strong>
          <span>Leave now. Follow the route below.</span>
        </div>
      </div>
    )
  }

  return (
    <div className="alert alert-calm" role="status">
      <WarningIcon className="alert-icon" />
      <div className="alert-text">
        <strong>{title} nearby</strong>
        <span className="num">
          {noun} is {near.km.toFixed(1)} km {near.direction} of you.
        </span>
      </div>
    </div>
  )
}
