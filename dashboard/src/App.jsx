import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  compareTraffic,
  deleteHazards,
  getClosedRoads,
  getEvacuees,
  getForecast,
  getHazards,
  getReports,
  getShelters,
  getSimState,
  getTraffic,
  pauseSim,
  resetSim,
  resumeSim,
  setSimSpeed,
  setSimWind,
  setTrafficConfig,
  startSim,
} from './api.js'
import { POLL_MS, USE_FIXTURES } from './config.js'
import { forecastHorizon, hazardsForView, recordSnapshot } from './history.js'
import { dangerRings, unsafeShelterIds } from './evacuation.js'
import { nextCutoff, phoneRerouteCount } from './cutoff.js'
import MapView from './components/MapView.jsx'
import Header from './components/Header.jsx'
import IncidentBanner from './components/IncidentBanner.jsx'
import ControlsPanel from './components/ControlsPanel.jsx'
import HistoryBar from './components/HistoryBar.jsx'
import SidePanel from './components/SidePanel.jsx'
import Dialog from './components/Dialog.jsx'
import ReportsList from './components/ReportsList.jsx'
import NotifyForm from './components/NotifyForm.jsx'

// Backend errors come back as { error, message } (contract). The raw message can be
// misleading (a tornado start says "Flood deferred"), so known codes get plain text.
function simErrorText(err) {
  if (err.code === 'unsupported_scenario') return "The backend can't simulate this hazard yet."
  return `The backend refused this: ${err.message}`
}

export default function App() {
  const [mode, setMode] = useState('drill')
  const [hazardKind, setHazardKind] = useState('wildfire')
  const [startPoint, setStartPoint] = useState(null) // { lng, lat } picked on the map
  const [showPredicted, setShowPredicted] = useState(true)
  const [onlyPriority, setOnlyPriority] = useState(false) // map shows only priority residents
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [reports, setReports] = useState(null)
  const [sim, setSim] = useState(null) // GET /sim/state
  const [focus, setFocus] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [connectionError, setConnectionError] = useState(false)
  const [forecast, setForecast] = useState(null) // GET /forecast
  const [evacuees, setEvacuees] = useState(null) // GET /evacuees: phones that set a location
  const [traffic, setTraffic] = useState(null) // GET /traffic (roads + metrics)
  const [closedRoads, setClosedRoads] = useState(null) // GET /roads/closed
  const [trafficBusy, setTrafficBusy] = useState(false)
  const [viewing, setViewing] = useState(null) // history slider: null = live, else a sim minute
  const [popup, setPopup] = useState(null) // 'reports' | 'notify' | null: which centred pop-up is open
  const snapshots = useRef(new Map()) // sim_time → hazard features, for the slider
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
      // A failed forecast only hides the predicted path; it isn't a lost connection.
      const fc = await getForecast().catch(() => null)
      // Same for evacuees: a failure only hides the phone dots until the next poll.
      const ev = await getEvacuees().catch(() => null)
      const tr = await getTraffic().catch(() => null)
      const cr = await getClosedRoads().catch(() => null)
      if (ev) setEvacuees(ev)
      if (tr) setTraffic(tr)
      if (cr) setClosedRoads(cr)
      if (h.status === 'fulfilled') setHazards(h.value)
      if (s.status === 'fulfilled') setShelters(s.value)
      if (r.status === 'fulfilled') setReports(r.value)
      if (st.status === 'fulfilled') setSim(st.value)
      setForecast(fc)
      if (h.status === 'fulfilled' && st.status === 'fulfilled') recordSnapshot(snapshots.current, h.value, st.value)
      if (results.some((x) => x.status === 'fulfilled')) setLastUpdated(new Date())
      setConnectionError(results.some((x) => x.status === 'rejected'))
    } finally {
      inFlight.current = false
    }
  }, [])

  // Run a sim command, then redraw straight away instead of waiting for the next poll.
  // A refusal from the backend (it answered with an error) is shown by the controls;
  // only a failed request (no answer) counts as the backend being unreachable.
  const [simError, setSimError] = useState(null)
  const run = useCallback(
    async (fn) => {
      try {
        await fn()
        setSimError(null)
      } catch (err) {
        if (err.code) setSimError(simErrorText(err))
        else setConnectionError(true)
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
        setViewing(null) // resuming or starting goes back to live
        if (sim?.state === 'paused') return resumeSim()
        if (!startPoint) return
        const where = { lat: startPoint.lat, lon: startPoint.lng }
        // fuel_dryness is no longer sent; the backend uses its default (0.7 in the contract).
        // `tornado` is not a contract v1 scenario yet; it reuses wind_kmh / wind_from_deg
        // as the storm's travel speed and direction.
        await startSim(
          hazardKind === 'tornado'
            ? {
                scenario: 'tornado',
                ...where,
                wind_kmh: conditions.windKmh,
                wind_from_deg: conditions.windFrom,
                ef_rating: conditions.efRating,
              }
            : {
                scenario: 'wildfire',
                ...where,
                wind_kmh: conditions.windKmh,
                wind_from_deg: conditions.windFrom,
                humidity_pct: conditions.humidity,
              },
        )
        await setSimSpeed(speed)
        // Turn traffic on at start so the map shows jammed roads without a second step.
        // Default to thousands so judges see gridlock + reroutes as soon as the
        // disaster drops (slider value wins if they already tuned Traffic).
        await setTrafficConfig({
          enabled: true,
          anti_gridlock: true,
          simulated_count: conditions.trafficCount ?? traffic?.simulated_count ?? 2000,
        })
      }),
    [run, sim, startPoint, hazardKind, traffic],
  )

  const reset = useCallback(
    () =>
      run(async () => {
        await resetSim()
        await deleteHazards()
        // Turn traffic paint off so the map isn't jammed before the next fire.
        await setTrafficConfig({ enabled: false }).catch(() => null)
        setTraffic(null)
        setClosedRoads(null)
        setStartPoint(null)
        setViewing(null)
        snapshots.current.clear()
      }),
    [run],
  )

  const changeSpeed = useCallback((multiplier) => run(() => setSimSpeed(multiplier)), [run])

  const changeWind = useCallback(
    (windKmh, windFrom) => run(() => setSimWind(windKmh, windFrom)),
    [run],
  )

  const changeTraffic = useCallback(
    async (patch) => {
      setTrafficBusy(true)
      try {
        const next = await setTrafficConfig(patch)
        // Full /traffic (with edges) for the map; config only returns state.
        const full = await getTraffic().catch(() => next)
        setTraffic(full)
        setSimError(null)
      } catch (err) {
        if (err.code) setSimError(simErrorText(err))
        else setConnectionError(true)
      } finally {
        setTrafficBusy(false)
      }
    },
    [],
  )

  const runCompare = useCallback(async () => {
    setTrafficBusy(true)
    try {
      await compareTraffic()
      const full = await getTraffic()
      setTraffic(full)
      setSimError(null)
    } catch (err) {
      if (err.code) setSimError(simErrorText(err))
      else setConnectionError(true)
    } finally {
      setTrafficBusy(false)
    }
  }, [])

  // Dragging the history slider pauses the sim (spec), so "now" holds still.
  const scrub = useCallback(
    (t) => {
      setViewing(t)
      if (sim?.state === 'running') run(() => pauseSim())
    },
    [sim, run],
  )
  // Snapshots only change inside refresh(), which also sets `hazards`, so these deps cover them.
  const shownHazards = useMemo(
    () => hazardsForView(hazards, forecast, snapshots.current, viewing),
    [hazards, forecast, viewing],
  )
  // Shelters the fire is in, or is forecast to come within the evacuation buffer of.
  // From the live fire + forecast, not the slider, so a warning doesn't come and go
  // while scrubbing.
  const unsafeShelters = useMemo(
    () => unsafeShelterIds(shelters, dangerRings(hazards, forecast?.outlines)),
    [shelters, hazards, forecast],
  )
  const cutoff = useMemo(() => nextCutoff(shelters, hazards, forecast), [shelters, hazards, forecast])
  const phoneReroutes = useMemo(() => phoneRerouteCount(evacuees), [evacuees])

  // Picking a report closes the pop-up so the map can be seen centring on it.
  const focusReport = useCallback((feature) => {
    setFocus({ id: feature.id, lngLat: feature.geometry.coordinates, at: Date.now() })
    setPopup(null)
  }, [])
  const closePopup = useCallback(() => setPopup(null), [])

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
      <IncidentBanner hazards={hazards} mode={mode} sim={sim} cutoff={cutoff} closedCount={closedRoads?.count} />
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
          onWindChange={changeWind}
          error={simError}
          showPredicted={showPredicted}
          onShowPredictedChange={setShowPredicted}
          reportCount={reports?.features?.length ?? 0}
          onOpenReports={() => setPopup('reports')}
          onOpenNotify={() => setPopup('notify')}
          onlyPriority={onlyPriority}
          onOnlyPriorityChange={setOnlyPriority}
          traffic={traffic}
          trafficBusy={trafficBusy}
          onTrafficConfig={changeTraffic}
          onTrafficCompare={runCompare}
        />
        <main className="centre">
          <MapView
            hazards={shownHazards}
            nowLabel={viewing == null ? 'Now' : `T+${viewing}`}
            shelters={shelters}
            unsafeShelters={unsafeShelters}
            evacuees={evacuees}
            onlyPriority={onlyPriority}
            reports={reports}
            focus={focus}
            startPoint={startPoint}
            showPredicted={showPredicted}
            traffic={traffic}
            closedRoads={closedRoads}
            onMapClick={pickStart}
          />
          <HistoryBar
            now={simIdle ? null : (hazards?.sim_time ?? null)}
            horizon={forecastHorizon(forecast)}
            viewing={viewing}
            onScrub={scrub}
            onLive={() => setViewing(null)}
          />
        </main>
        <SidePanel
          shelters={shelters}
          traffic={traffic}
          closedCount={closedRoads?.count}
          phoneReroutes={phoneReroutes}
          peopleAtRisk={evacuees?.features?.length ?? null}
        />
      </div>
      <Dialog open={popup === 'reports'} title="Reports" onClose={closePopup}>
        <ReportsList reports={reports} onSelect={focusReport} />
      </Dialog>
      <Dialog open={popup === 'notify'} title="Notify residents" onClose={closePopup}>
        <NotifyForm open={popup === 'notify'} />
      </Dialog>
    </div>
  )
}
