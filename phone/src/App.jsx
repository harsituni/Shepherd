import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getHazards,
  getNotifications,
  getRoute,
  getShelters,
  getSimState,
  postEvacuee,
  postReport,
  withChoice,
} from './api.js'
import { POLL_MS } from './config.js'
import { evacueeId, useEvacuation } from './evacuate.js'
import { isCurrentCore, nearestHazard } from './geo.js'
import { placeName } from './placeName.js'
import { nextClock } from './simClock.js'
import AlertBanner from './components/AlertBanner.jsx'
import EvacCard from './components/EvacCard.jsx'
import MapView from './components/MapView.jsx'
import { AlertsTab, mostSevere, NotificationPopup } from './components/Notifications.jsx'
import RouteTab from './components/RouteTab.jsx'
import { CrookIcon } from './components/icons.jsx'
import ReportSheet from './components/ReportSheet.jsx'
import { SHEPHERD_VERSION } from './version.js'

// Resolves to [lon, lat], or null if unavailable, denied or slow.
// Browsers only allow this on https or localhost.
function deviceLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      (p) => resolve([p.coords.longitude, p.coords.latitude]),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    )
  })
}

const TABS = [
  ['route', 'Route'],
  ['gov', 'Alerts'],
]

export default function App() {
  const [tab, setTab] = useState('route')
  const [location, setLocation] = useState(null) // [lon, lat]
  const [route, setRoute] = useState(null)
  const [routeError, setRouteError] = useState(null)
  const [chosen, setChosen] = useState(null) // shelter_id of the route card the user picked
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [focusKey, setFocusKey] = useState(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState(null)
  const [notifications, setNotifications] = useState([])
  const [popup, setPopup] = useState(null)
  const [clock, setClock] = useState(null) // sim clock for the leave-by countdown
  const seenNotes = useRef(new Set())
  const toastTimer = useRef(null)
  const locationRef = useRef(location)
  const evacuatingRef = useRef(false)
  const [areaName, setAreaName] = useState('Edmonton')
  const areaTimer = useRef(null)
  const areaAbort = useRef(null)

  useEffect(() => {
    locationRef.current = location
  }, [location])

  // Header place name follows the map. Wait until panning/zooming settles,
  // then look it up; keep the previous name if the lookup fails.
  const onViewChange = useCallback((center, zoom) => {
    clearTimeout(areaTimer.current)
    areaTimer.current = setTimeout(async () => {
      areaAbort.current?.abort()
      const ctrl = new AbortController()
      areaAbort.current = ctrl
      try {
        const name = await placeName(center, zoom, ctrl.signal)
        if (name && !ctrl.signal.aborted) setAreaName(name)
      } catch {
        // offline or rate-limited: leave the current name
      }
    }, 600)
  }, [])

  useEffect(
    () => () => {
      clearTimeout(areaTimer.current)
      areaAbort.current?.abort()
    },
    [],
  )

  const showToast = useCallback((text, ms = 3000) => {
    clearTimeout(toastTimer.current)
    setToast(text)
    toastTimer.current = setTimeout(() => setToast(null), ms)
  }, [])

  const refresh = useCallback(async () => {
    const [h, s, n, st] = await Promise.allSettled([getHazards(), getShelters(), getNotifications(), getSimState()])
    if (h.status === 'fulfilled') setHazards(h.value)
    // Sim clock from /sim/state; older backends without it fall back to /hazards' sim_time at 1x.
    if (st.status === 'fulfilled' && st.value) setClock((c) => nextClock(c, st.value))
    else if (h.status === 'fulfilled') setClock((c) => nextClock(c, { sim_time: h.value?.sim_time }))
    if (s.status === 'fulfilled') setShelters(s.value)
    if (n.status === 'fulfilled') {
      const fresh = n.value.filter((x) => !seenNotes.current.has(x.id))
      if (fresh.length) {
        fresh.forEach((x) => seenNotes.current.add(x.id))
        setNotifications(n.value)
        setPopup(mostSevere(fresh)) // pop up the most important new one
      }
    }

    const loc = locationRef.current
    if (!loc) return
    // While evacuating the dot moves every frame, so a response for where it was
    // 2 s ago is still the one to show. Otherwise a moved pin makes it stale.
    const stale = () => !evacuatingRef.current && locationRef.current !== loc
    try {
      const r = await getRoute(loc[1], loc[0])
      if (stale()) return
      setRoute(r)
      setRouteError(null)
    } catch (err) {
      if (stale()) return
      setRoute(null)
      setRouteError(err.code === 'no_route' ? 'no_route' : 'network')
    }
  }, [])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const id = setInterval(refresh, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [refresh])

  const setLocationAndRoute = useCallback(
    (lngLat) => {
      locationRef.current = lngLat
      setLocation(lngLat)
      setRoute(null)
      setRouteError(null)
      setChosen(null) // a new location starts from the recommended route
      setFocusKey(Date.now())
      refresh()
    },
    [refresh],
  )

  const sendReport = useCallback(
    async (kind, note) => {
      let loc = locationRef.current
      // Need help must always work: without a pinned location, ask the device for one.
      if (!loc && kind === 'sos') {
        setSending(true)
        loc = await deviceLocation()
        setSending(false)
        if (!loc) {
          showToast("Couldn't get your location. Tap the map where you are, or call 911.")
          setTab('route')
          return false
        }
        setLocationAndRoute(loc)
      }
      if (!loc) {
        showToast('Tap the map to set your location first.')
        setTab('route')
        return false
      }
      setSending(true)
      try {
        await postReport({ kind, lat: loc[1], lon: loc[0], note })
        showToast(
          kind === 'safe' ? "Marked as safe. Thank you." : kind === 'sos' ? 'Help request sent. Responders can see your location.' : 'Report sent. Thank you.',
        )
        return true
      } catch {
        showToast("Couldn't send. Check your connection and try again.")
        return false
      } finally {
        setSending(false)
      }
    },
    [showToast, setLocationAndRoute],
  )

  // The route on screen: the card the user picked, or the backend's best.
  const { shown, lost } = withChoice(route, chosen)
  const shownRef = useRef(shown)
  useEffect(() => {
    shownRef.current = shown
  }, [shown])

  // "Start evacuating" (issue #56): a simulated drive along the chosen route, or the
  // phone's real GPS. Either way the dot moves without resetting the route choice.
  const [evacMode, setEvacMode] = useState('sim') // 'sim' | 'gps'
  const moveTo = useCallback((lngLat) => {
    if (!lngLat) return
    locationRef.current = lngLat
    setLocation(lngLat)
  }, [])
  const gpsFailed = useCallback((message) => showToast(message, 6000), [showToast])
  const { trip, start: startTrip, stop: stopTrip } = useEvacuation({ clock, onMove: moveTo, onError: gpsFailed })
  const evacuating = trip != null
  useEffect(() => {
    evacuatingRef.current = evacuating
  }, [evacuating])

  // Heartbeat to POST /evacuees every ~2 s while evacuating (simulated or GPS), so the
  // dashboard shows this phone like any other.
  useEffect(() => {
    if (!evacuating) return
    const id = evacueeId()
    const beat = () => {
      const loc = locationRef.current
      const r = shownRef.current
      if (!loc) return
      postEvacuee({
        id,
        lat: loc[1],
        lon: loc[0],
        route_id: r?.route_id ?? null,
        route_status: r?.status ?? null,
        shelter_id: r?.shelter_id ?? null,
      }).catch(() => {}) // a missed beat is fine; the next one follows in 2 s
    }
    beat()
    const timer = setInterval(beat, POLL_MS)
    return () => clearInterval(timer)
  }, [evacuating])

  // During a wildfire the evacuation card (leave-by countdown) takes the banner's place.
  const wildfire =
    route?.leave_by_sim_min != null ||
    (hazards?.features ?? []).some((f) => isCurrentCore(f) && f.properties.kind === 'wildfire')

  return (
    <div className="phone">
      <header className="header">
        <span className="brand">
          <span className="brand-mark" aria-hidden="true">
            <CrookIcon />
          </span>
          Shepherd
        </span>
        <span className="header-meta">
          <span className="city" aria-live="polite" title={areaName}>
            {areaName}
          </span>
          <span className="build-ver num" title="Git revision for this UI build">
            {SHEPHERD_VERSION}
          </span>
        </span>
      </header>

      {popup && <NotificationPopup key={popup.id} notification={popup} onDismiss={() => setPopup(null)} />}

      {wildfire ? (
        <EvacCard
          location={location}
          route={shown}
          routeError={routeError}
          near={location ? nearestHazard(location, hazards) : null}
          clock={clock}
          trip={trip}
        />
      ) : (
        <AlertBanner hazards={hazards} location={location} notifications={notifications} />
      )}

      <nav className="tabs" role="tablist" aria-label="Sections">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls="tab-panel"
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <main className="content" id="tab-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {/* Keep the map mounted across tab switches; just hide it. */}
        <div hidden={tab !== 'route'}>
          <RouteTab
            map={
              <MapView
                hazards={hazards}
                shelters={shelters}
                route={shown}
                location={location}
                onTap={evacuating ? undefined : setLocationAndRoute}
                onViewChange={onViewChange}
                focusKey={focusKey}
                tall={!location}
              />
            }
            hazards={hazards}
            location={location}
            route={shown}
            lost={lost}
            routeError={routeError}
            shelters={shelters}
            onChoose={(shelterId) => {
              setChosen(shelterId)
              setFocusKey(Date.now()) // frame the newly picked route
            }}
            trip={trip}
            evacMode={evacMode}
            onEvacMode={setEvacMode}
            onStartEvacuating={() => {
              setFocusKey(Date.now()) // frame the route the dot will follow
              startTrip(evacMode, shown)
            }}
            onStopEvacuating={stopTrip}
          />
        </div>
        {tab === 'gov' && <AlertsTab notifications={notifications} />}
      </main>

      <div className="action-bar">
        <button
          type="button"
          className="action"
          disabled={!location || sending}
          onClick={() => setSheetOpen(true)}
        >
          Report hazard
        </button>
        <button
          type="button"
          className="action"
          disabled={!location || sending}
          onClick={() => sendReport('safe')}
        >
          I'm safe
        </button>
        <button
          type="button"
          className="action action-help"
          disabled={sending}
          onClick={() => sendReport('sos')}
        >
          Need help
        </button>
      </div>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      {sheetOpen && (
        <ReportSheet
          sending={sending}
          onClose={() => setSheetOpen(false)}
          onSubmit={async ({ kind, note }) => {
            if (await sendReport(kind, note)) setSheetOpen(false)
            else if (!locationRef.current) setSheetOpen(false)
          }}
        />
      )}
    </div>
  )
}
