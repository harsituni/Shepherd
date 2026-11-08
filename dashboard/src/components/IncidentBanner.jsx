// `flood` stays labelled for live feeds; the simulation itself offers wildfire and tornado.
const KIND_LABEL = { wildfire: 'Wildfire', tornado: 'Tornado', flood: 'Flood' }

function tornadoLine(sim, core) {
  const t = sim?.tornado ?? (core?.properties?.ef_label ? core.properties : null)
  if (!t) return null
  const bits = [
    t.ef_label && `${t.ef_label}${t.ef_peak_label && t.ef_peak_label !== t.ef_label ? ` (peak ${t.ef_peak_label})` : ''}`,
    t.phase,
    t.wind_est_kmh != null && `${t.wind_est_kmh} km/h winds`,
    t.path_width_m != null && `${t.path_width_m} m wide`,
    t.forward_speed_kmh != null && `${t.forward_speed_kmh} km/h forward`,
    t.track_km != null && `${t.track_km} km track`,
  ].filter(Boolean)
  return bits.join(' · ')
}

// Built from /hazards (+ /sim/state for tornado EF stats).
export default function IncidentBanner({ hazards, mode, sim }) {
  const features = (hazards?.features ?? []).filter((f) => f.properties?.predicted_min == null)
  const modeLabel = mode === 'drill' ? 'simulation' : 'live'

  if (features.length === 0) {
    return (
      <div className="banner">
        <span className="banner-dot idle" aria-hidden="true" />
        <strong>No active hazards</strong>
        <span className="banner-sub">
          {mode === 'drill' ? 'Pick a hazard and click the map to start a simulation' : 'Monitoring live feeds'}
        </span>
      </div>
    )
  }

  const kinds = [...new Set(features.map((f) => f.properties.kind))]
  const title = kinds.map((k) => KIND_LABEL[k] ?? k).join(' and ')
  const zones = features.length
  const core = features.find((f) => f.properties?.kind === 'tornado' && f.properties?.zone === 'core')
  const tornado = tornadoLine(sim, core)

  return (
    <div className={`banner${core ? ' banner-tornado' : ''}`}>
      <span className={`banner-dot${core ? ' tornado' : ''}`} aria-hidden="true" />
      <strong>
        {core?.properties?.ef_label ? `${core.properties.ef_label} tornado` : title} {modeLabel}
      </strong>
      <span className="banner-sub num">
        {tornado
          ? tornado
          : `${zones} active ${zones === 1 ? 'zone' : 'zones'}${
              hazards.sim_time != null ? ` · T+${hazards.sim_time} min` : ''
            }`}
        {tornado && hazards.sim_time != null ? ` · T+${hazards.sim_time} min` : ''}
      </span>
    </div>
  )
}
