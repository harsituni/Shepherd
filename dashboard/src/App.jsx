import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteHazards,
  getHazards,
  getReports,
  getShelters,
  getSimState,
  pauseSim,
  resetSim,
  resumeSim,
  setSimSpeed,
  startSim,
} from './api.js'
import { POLL_MS, USE_FIXTURES } from './config.js'
import MapView from './components/MapView.jsx'
import Header from './components/Header.jsx'
import IncidentBanner from './components/IncidentBanner.jsx'
import ControlsPanel from './components/ControlsPanel.jsx'
import HistoryBar from './components/HistoryBar.jsx'
import SidePanel from './components/SidePanel.jsx'

export default function App() {
  const [mode, setMode] = useState('drill')
  const [hazardKind, setHazardKind] = useState('wildfire')
  const [startPoint, setStartPoint] = useState(null) // { lng, lat } picked on the map
  const [showPredicted, setShowPredicted] = useState(true)
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [reports, setReports] = useState(null)
  const [sim, setSim] = useState(null) // GET /sim/state
  const [focus, setFocus] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [connectionError, setConnectionError] = useState(false)
  const inFlight = useRef(false)

  // Re-fetch everything the backend owns. Each result is applied on its own, so one
  // failing endpoint (e.g. /reports or /sim/state before the backend has it) doesn't
  // freeze the others. A tick is skipped if the previous one is still in flight.
  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const results = await Promise.allSettled([getHazards(), getShelters(), getReports(), getSimState()])
      const [h, s, r, st] = results
      if (h.status === 'fulfilled') setHazards(h.value)
      if (s.status === 'fulfilled') setShelters(s.value)
      if (r.status === 'fulfilled') setReports(r.value)
      if (st.status === 'fulfilled') setSim(st.value)
      if (results.some((x) => x.status === 'fulfilled')) setLastUpdated(new Date())
      setConnectionError(results.some((x) => x.status === 'rejected'))
    } finally {
      inFlight.current = false
    }
  }, [])

  // Run a sim command, then redraw straight away instead of waiting for the next poll.
  const run = useCallback(
    async (fn) => {
      try {
        await fn()
      } catch {
        setConnectionError(true)
      }
      await refresh()
    },
    [refresh],
  )

  const simIdle = !sim || sim.state === 'idle'
  const canSimulate = mode === 'drill'

  // Map click picks where the hazard starts. It can only move before the simulation starts.
  const pickStart = useCallback(
    ({ lng, lat }) => {
      if (canSimulate && simIdle) setStartPoint({ lng, lat })
    },
    [canSimulate, simIdle],
  )

  const play = useCallback(
    (conditions, speed) =>
      run(async () => {
        if (sim?.state === 'running') return pauseSim()
        if (sim?.state === 'paused') return resumeSim()
        if (!startPoint) return
        const where = { lat: startPoint.lat, lon: startPoint.lng }
        // fuel_dryness is no longer sent; the backend uses its default (0.7 in the contract).
        // `tornado` is not a contract v1 scenario yet; it reuses wind_kmh / wind_from_deg
        // as the storm's travel speed and direction.
        await startSim(
          hazardKind === 'tornado'
            ? { scenario: 'tornado', ...where, wind_kmh: conditions.windKmh, wind_from_deg: conditions.windFrom }
            : {
                scenario: 'wildfire',
                ...where,
                wind_kmh: conditions.windKmh,
                wind_from_deg: conditions.windFrom,
                humidity_pct: conditions.humidity,
              },
        )
        await setSimSpeed(speed)
      }),
    [run, sim, startPoint, hazardKind],
  )

  const reset = useCallback(
    () =>
      run(async () => {
        await resetSim()
        await deleteHazards()
        setStartPoint(null)
      }),
    [run],
  )

  const changeSpeed = useCallback((multiplier) => run(() => setSimSpeed(multiplier)), [run])

  const focusReport = useCallback((feature) => {
    setFocus({ id: feature.id, lngLat: feature.geometry.coordinates, at: Date.now() })
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
        <ControlsPanel
          canSimulate={canSimulate}
          hazardKind={hazardKind}
          onHazardKindChange={setHazardKind}
          sim={sim}
          startPoint={startPoint}
          onPlay={play}
          onReset={reset}
          onSpeedChange={changeSpeed}
          showPredicted={showPredicted}
          onShowPredictedChange={setShowPredicted}
        />
        <main className="centre">
          <MapView
            hazards={hazards}
            shelters={shelters}
            reports={reports}
            focus={focus}
            startPoint={startPoint}
            showPredicted={showPredicted}
            onMapClick={pickStart}
          />
          <HistoryBar simTime={hazards?.sim_time} />
        </main>
        <SidePanel shelters={shelters} reports={reports} onReportSelect={focusReport} />
      </div>
    </div>
  )
}
