import { useCallback, useEffect, useRef, useState } from 'react'
import { getHazards, getReports, getShelters, postHazard } from './api.js'
import { DEFAULT_RADIUS_M, POLL_MS, USE_FIXTURES } from './config.js'
import MapView from './components/MapView.jsx'
import Header from './components/Header.jsx'
import IncidentBanner from './components/IncidentBanner.jsx'
import ControlsPanel from './components/ControlsPanel.jsx'
import HistoryBar from './components/HistoryBar.jsx'
import SidePanel from './components/SidePanel.jsx'

export default function App() {
  const [mode, setMode] = useState('drill')
  const [hazardKind, setHazardKind] = useState('wildfire')
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [reports, setReports] = useState(null)
  const [focus, setFocus] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [connectionError, setConnectionError] = useState(false)
  const inFlight = useRef(false)

  // Re-fetch hazards, shelters and reports together. Each one is applied on its own,
  // so one failing endpoint (e.g. /reports before the backend has it) doesn't freeze
  // the others. A tick is skipped if the previous one is still in flight.
  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const [h, s, r] = await Promise.allSettled([getHazards(), getShelters(), getReports()])
      if (h.status === 'fulfilled') setHazards(h.value)
      if (s.status === 'fulfilled') setShelters(s.value)
      if (r.status === 'fulfilled') setReports(r.value)
      const results = [h, s, r]
      if (results.some((x) => x.status === 'fulfilled')) setLastUpdated(new Date())
      setConnectionError(results.some((x) => x.status === 'rejected'))
    } finally {
      inFlight.current = false
    }
  }, [])

  // Clicking a report in the side panel centres the map on it.
  const focusReport = useCallback((feature) => {
    setFocus({ id: feature.id, lngLat: feature.geometry.coordinates, at: Date.now() })
  }, [])

  // Map click -> POST /hazards, then redraw straight away instead of waiting for the next poll.
  const placeHazard = useCallback(
    async ({ lng, lat }) => {
      try {
        await postHazard({ kind: hazardKind, lat, lon: lng, radius_m: DEFAULT_RADIUS_M })
        await refresh()
      } catch {
        setConnectionError(true)
      }
    },
    [hazardKind, refresh],
  )

  useEffect(() => {
    // Kick off the first poll, then keep polling every POLL_MS.
    const first = setTimeout(refresh, 0)
    const id = setInterval(refresh, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [refresh])

  return (
    <div className="app">
      <Header
        mode={mode}
        onModeChange={setMode}
        lastUpdated={lastUpdated}
        connectionError={connectionError}
        sampleData={USE_FIXTURES}
      />
      <IncidentBanner hazards={hazards} mode={mode} />
      <div className="layout">
        <ControlsPanel hazardKind={hazardKind} onHazardKindChange={setHazardKind} />
        <main className="centre">
          <MapView
            hazards={hazards}
            shelters={shelters}
            reports={reports}
            focus={focus}
            onMapClick={placeHazard}
          />
          <HistoryBar simTime={hazards?.sim_time} />
        </main>
        <SidePanel shelters={shelters} reports={reports} onReportSelect={focusReport} />
      </div>
    </div>
  )
}
