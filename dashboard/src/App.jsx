import { useCallback, useEffect, useState } from 'react'
import { getHazards, getShelters, postHazard } from './api.js'
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
  const [lastUpdated, setLastUpdated] = useState(null)
  const [connectionError, setConnectionError] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [h, s] = await Promise.all([getHazards(), getShelters()])
      setHazards(h)
      setShelters(s)
      setLastUpdated(new Date())
      setConnectionError(false)
    } catch {
      setConnectionError(true)
    }
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
          <MapView hazards={hazards} shelters={shelters} onMapClick={placeHazard} />
          <HistoryBar simTime={hazards?.sim_time} />
        </main>
        <SidePanel shelters={shelters} />
      </div>
    </div>
  )
}
