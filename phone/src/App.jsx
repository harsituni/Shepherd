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
import { useEvacuation, useHeartbeat } from './evacuate.js'
import { isCurrentCore, nearestHazard } from './geo.js'
import { placeName } from './placeName.js'
import { nextClock } from './simClock.js'
import AlertBanner from './components/AlertBanner.jsx'
import EvacCard from './components/EvacCard.jsx'
import MapView from './components/MapView.jsx'
import { mostSevere, NotificationPopup } from './components/Notifications.jsx'
import MapScreen from './components/MapScreen.jsx'
import { MapKey, RouteDetails, RouteMore } from './components/RouteTab.jsx'
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

export default function App() {
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

  const refreshBusy = useRef(false)

  const refresh = useCallback(async () => {
    // Skip stacked polls while a slow /route is still in flight (was stacking
    // every 2s and flashing "Reconnecting…" when the backend took longer).
    if (refreshBusy.current) return
    refreshBusy.current = true
    try {
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
      if (err.code !== 'no_route') {
        setRouteError('network')
        return
      }
    } finally {
      refreshBusy.current = false
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
          return false
        }
        setLocationAndRoute(loc)
      }
      if (!loc) {
        showToast('Tap the map to set your location first.')
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

  // Heartbeat to POST /evacuees every ~2 s once the user has set a location (by tapping
  // the map, a preset, or Need help) and while evacuating (simulated or GPS), so the
  // dashboard marks where they are. The backend drops a phone after 30 s without a
  // beat, so it keeps beating while a location is set.
  const readHeartbeat = useCallback(() => {
    const loc = locationRef.current
    if (!loc) return null
    const r = shownRef.current
    return {
      lat: loc[1],
      lon: loc[0],
      route_id: r?.route_id ?? null,
      route_status: r?.status ?? null,
      shelter_id: r?.shelter_id ?? null,
    }
  }, [])
  useHeartbeat({ active: evacuating || location != null, everyMs: POLL_MS, read: readHeartbeat, send: postEvacuee })

  // During a wildfire the evacuation card (leave-by countdown) takes the banner's place.
  const wildfire =
    route?.leave_by_sim_min != null ||
    (hazards?.features ?? []).some((f) => isCurrentCore(f) && f.properties.kind === 'wildfire')

  const detailProps = {
    location,
    route: shown,
    lost,
    routeError,
    shelters,
    onChoose: (shelterId) => {
      setChosen(shelterId)
      setFocusKey(Date.now()) // frame the newly picked route
    },
    trip,
    evacMode,
    onEvacMode: setEvacMode,
    onStartEvacuating: () => {
      setFocusKey(Date.now()) // frame the route the dot will follow
      startTrip(evacMode, shown)
    },
    onStopEvacuating: stopTrip,
  }

  return (
    <div className="phone">
      {popup && <NotificationPopup key={popup.id} notification={popup} onDismiss={() => setPopup(null)} />}
      <MapScreen
        renderMap={(framePadding) => (
          <MapView
            hazards={hazards}
            shelters={shelters}
            route={shown}
            location={location}
            onTap={evacuating ? undefined : setLocationAndRoute}
            onViewChange={onViewChange}
            focusKey={focusKey}
            framePadding={framePadding}
          />
        )}
        alert={
          wildfire ? (
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
          )
        }
        details={<RouteDetails {...detailProps} />}
        more={<RouteMore route={shown} shelters={shelters} trip={trip} evacMode={evacMode} />}
        mapKey={<MapKey hazards={hazards} shelters={shelters} route={shown} location={location} />}
        areaName={areaName}
        notifications={notifications}
        location={location}
        route={shown}
        routeError={routeError}
        trip={trip}
        version={SHEPHERD_VERSION}
        actions={{
          report: () => setSheetOpen(true),
          safe: () => sendReport('safe'),
          help: () => sendReport('sos'),
          canReport: !!location && !sending,
          sending,
        }}
      />

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
