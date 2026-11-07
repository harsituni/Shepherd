const KIND_LABEL = { wildfire: 'Wildfire', flood: 'Flood' }

// Built only from /hazards data: hazard kinds, zone count and sim_time.
export default function IncidentBanner({ hazards, mode }) {
  const features = hazards?.features ?? []
  const modeLabel = mode === 'drill' ? 'drill' : 'live'

  if (features.length === 0) {
    return (
      <div className="banner">
        <span className="banner-dot idle" aria-hidden="true" />
        <strong>No active hazards</strong>
        <span className="banner-sub">
          {mode === 'drill' ? 'Pick a hazard and click the map to start a drill' : 'Monitoring live feeds'}
        </span>
      </div>
    )
  }

  const kinds = [...new Set(features.map((f) => f.properties.kind))]
  const title = kinds.map((k) => KIND_LABEL[k] ?? k).join(' and ')
  const zones = features.length

  return (
    <div className="banner">
      <span className="banner-dot" aria-hidden="true" />
      <strong>
        {title} {modeLabel}
      </strong>
      <span className="banner-sub num">
        {zones} active {zones === 1 ? 'zone' : 'zones'}
        {hazards.sim_time != null && ` · T+${hazards.sim_time} min`}
      </span>
    </div>
  )
}
