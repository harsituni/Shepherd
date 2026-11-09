// Tornado simulation is a beta feature, so its banner says so.
const KIND_LABEL = { wildfire: 'Wildfire', tornado: 'Tornado (beta)' }

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

// Built from /hazards (+ /sim/state for tornado EF stats) and forecast cut-off warnings.
export default function IncidentBanner({ hazards, mode, sim, cutoff = null, closedCount = null }) {
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
  const closedBit =
    closedCount > 0 ? `${closedCount.toLocaleString()} road${closedCount === 1 ? '' : 's'} closed` : null
  const warn = cutoff?.message

  return (
    <div className={`banner${core ? ' banner-tornado' : ''}${warn ? ' banner-cutoff' : ''}`}>
      <span className={`banner-dot${core ? ' tornado' : ''}${warn ? ' warn' : ''}`} aria-hidden="true" />
      <strong>
        {core?.properties?.ef_label ? `${core.properties.ef_label} tornado` : title} {modeLabel}
        {core?.properties?.ef_label ? ' (beta)' : ''}
      </strong>
      <span className="banner-sub num">
        {warn
          ? warn
          : tornado
            ? tornado
            : `${zones} active ${zones === 1 ? 'zone' : 'zones'}${
                hazards.sim_time != null ? ` · T+${hazards.sim_time} min` : ''
              }`}
        {!warn && tornado && hazards.sim_time != null ? ` · T+${hazards.sim_time} min` : ''}
        {warn && hazards.sim_time != null ? ` · T+${hazards.sim_time} min` : ''}
        {closedBit ? ` · ${closedBit}` : ''}
      </span>
    </div>
  )
}
