import { useCallback, useEffect, useState } from 'react'
import { getHazards, getShelters } from './api.js'
import { POLL_MS, USE_FIXTURES } from './config.js'
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
          <div className="map-wrap" />
          <HistoryBar simTime={hazards?.sim_time} />
        </main>
        <SidePanel shelters={shelters} />
      </div>
    </div>
  )
}
