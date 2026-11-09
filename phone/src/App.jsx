import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getHazards,
  getReports,
  getNotifications,
  getRoute,
  getShelters,
  getSimState,
  getTrafficHint,
  postEvacuee,
  postReport,
  postPriority,
  deletePriority,
  withChoice,
} from './api.js'
import { MAP_CENTER, POLL_MS } from './config.js'
import { evacueeId, locateOnce, useEvacuation, useFollowGps, useHeartbeat, useWakeLock } from './evacuate.js'
import { dangerRings, demoteUnsafeRoute, evacZones, unsafeShelterIds } from './evacuation.js'
import { isCurrentCore, nearestHazard, pointInRing } from './geo.js'
import { noSafeRoute, shouldReroute } from './reroute.js'
import { placeName } from './placeName.js'
import { nextClock } from './simClock.js'
import { nextDeadline } from './leaveBy.js'
import AlertBanner from './components/AlertBanner.jsx'
import EvacCard from './components/EvacCard.jsx'
import MapView from './components/MapView.jsx'
import { mostSevere, NotificationPopup } from './components/Notifications.jsx'
import MapScreen from './components/MapScreen.jsx'
import { MapKey, RouteDetails, RouteMore } from './components/RouteTab.jsx'
import ReportSheet from './components/ReportSheet.jsx'
import PrioritySheet from './components/PrioritySheet.jsx'
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

// Keep leave-by from drifting later on the same recommended route (cleared when
// the pin changes, the best route changes, or nothing is recommended anymore).
function ratchetLeaveBy(prev, next) {
  if (!next) return next
  if (next.route_status && next.route_status !== 'viable') return next
  if (prev?.best_route_id && next.best_route_id && prev.best_route_id !== next.best_route_id) {
    return next
  }
  const was = prev?.leave_by_sim_min
  if (was == null) return next
  const now = next.leave_by_sim_min
  if (now == null || now > was) return { ...next, leave_by_sim_min: was }
  return next
}

// Priority registration is remembered on this phone (only the ID's last 4
// characters, never the full number) so it can be re-sent if the backend restarts.
const PRIORITY_KEY = 'shepherd.priority'
function loadPriority() {
  try {
    const v = JSON.parse(localStorage.getItem(PRIORITY_KEY) ?? 'null')
    return v?.id_type && v?.id_last4 && Array.isArray(v.needs) ? v : null
  } catch {
    return null
  }
}
function savePriority(v) {
  try {
    if (v) localStorage.setItem(PRIORITY_KEY, JSON.stringify(v))
    else localStorage.removeItem(PRIORITY_KEY)
  } catch {
    // storage blocked: it lasts for this page load
  }
}

export default function App() {
  const [location, setLocation] = useState(null) // [lon, lat]
  const [autoLocation, setAutoLocation] = useState(null) // the launch GPS fix, shown with the panel collapsed
  // Where the location was last *set* (tap, launch fix, Real GPS picked). The route panel
  // keys its open/closed state on this, so a pin that follows GPS doesn't reopen it.
  const [placeKey, setPlaceKey] = useState(null)
  const [route, setRoute] = useState(null)
  const [routeError, setRouteError] = useState(null)
  const [chosen, setChosen] = useState(null) // id of the route card the user picked
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [focusKey, setFocusKey] = useState(null)
  // Reporting a hazard is two steps: 'place' (tap the map where it is), then
  // 'details' (the sheet: type + note). reportAt is the placed spot.
  const [reportStep, setReportStep] = useState(null) // null | 'place' | 'details'
  const [reportAt, setReportAt] = useState(null) // [lon, lat]
  const [reports, setReports] = useState(null) // public hazard reports from every phone
  const [priorityOpen, setPriorityOpen] = useState(false)
  const [priority, setPriority] = useState(loadPriority) // { id_type, id_last4, needs, note } | null
  const [prioritySending, setPrioritySending] = useState(false)
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState(null)
  const [locating, setLocating] = useState(false) // waiting on a GPS fix
  const [notifications, setNotifications] = useState([])
  const [popup, setPopup] = useState(null)
  const [clock, setClock] = useState(null) // sim clock for the simulated drive
  // The leave-by deadline on this phone's clock (src/leaveBy.js); null = no countdown.
  const [deadline, setDeadline] = useState(null)
  const seenNotes = useRef(new Set())
  const toastTimer = useRef(null)
  const locationRef = useRef(location)
  const chosenRef = useRef(chosen)
  const evacuatingRef = useRef(false)
  const followingRef = useRef(false) // pin follows Real GPS without a trip
  const [areaName, setAreaName] = useState('Edmonton')
  const areaTimer = useRef(null)
  const areaAbort = useRef(null)

  useEffect(() => {
    locationRef.current = location
  }, [location])
  useEffect(() => {
    chosenRef.current = chosen
  }, [chosen])

  // Header place name follows the map. Wait until panning/zooming settles,
  // then look it up; keep the previous name if the lookup fails.
  const mapCenterRef = useRef(MAP_CENTER) // where a new report pin starts
  const onViewChange = useCallback((center, zoom) => {
    mapCenterRef.current = center
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
  const showToastRef = useRef(showToast)
  useEffect(() => {
    showToastRef.current = showToast
  }, [showToast])

  // Filled in once useEvacuation mounts; refresh reads these each poll.
  const tripRef = useRef(null)
  const rerouteRef = useRef(null)
  const noSafeToastAt = useRef(0)
  const trafficHintAt = useRef(0)
  const [trafficBanner, setTrafficBanner] = useState(null)

  const refreshBusy = useRef(false)

  const refresh = useCallback(async () => {
    // Skip stacked polls while a slow /route is still in flight (was stacking
    // every 2s and flashing "Reconnecting…" when the backend took longer).
    if (refreshBusy.current) return
    refreshBusy.current = true
    try {
      const [h, s, n, st, rp] = await Promise.allSettled([
        getHazards(),
        getShelters(),
        getNotifications(),
        getSimState(),
        getReports(),
      ])
      if (rp.status === 'fulfilled') setReports(rp.value)
      if (h.status === 'fulfilled') setHazards(h.value)
      // Sim clock from /sim/state; older backends without it fall back to /hazards' sim_time at 1x.
      if (st.status === 'fulfilled' && st.value) setClock((c) => nextClock(c, st.value))
      else if (h.status === 'fulfilled') setClock((c) => nextClock(c, { sim_time: h.value?.sim_time }))
      if (s.status === 'fulfilled') setShelters(s.value)
      if (n.status === 'fulfilled') {
        // "Residents inside hazard zone" updates only reach phones pinned inside a
        // wildfire evacuation zone; everything else goes to every phone.
        const here = locationRef.current
        const zones = evacZones(h.status === 'fulfilled' ? h.value : null).features
        const inZone = here != null && zones.some((z) => pointInRing(here, z.geometry.coordinates[0]))
        const mine = n.value.filter((x) => x.target !== 'zone' || inZone)
        const fresh = mine.filter((x) => !seenNotes.current.has(x.id))
        if (fresh.length) {
          fresh.forEach((x) => seenNotes.current.add(x.id))
          setNotifications(mine)
          setPopup(mostSevere(fresh)) // pop up the most important new one
        }
      }

      const loc = locationRef.current
      if (!loc) return
      // While evacuating (or following GPS) the dot keeps moving, so a response for where
      // it was a moment ago is still the one to show. Otherwise a moved pin makes it stale.
      const stale = () => !evacuatingRef.current && !followingRef.current && locationRef.current !== loc
      try {
        // Prefer the route we're actually driving so /route keeps it in `options`
        // even after it turns unsafe (needed to decide a mid-trip reroute).
        const drivingId =
          tripRef.current?.route?.route_id ?? tripRef.current?.route?.id ?? chosenRef.current
        let r = await getRoute(loc[1], loc[0], drivingId)
        if (stale()) return
        // Same yellow-zone rule as the map markers: never leave a painted-unsafe
        // centre as Clear / Recommended if /route is briefly still optimistic.
        if (h.status === 'fulfilled' && s.status === 'fulfilled') {
          const outlines = h.value?.forecast ?? []
          r = demoteUnsafeRoute(r, unsafeShelterIds(s.value, dangerRings(h.value, outlines)))
        }

        // Mid-trip: if the path we're on went bad, switch onto the new best from here.
        if (evacuatingRef.current && tripRef.current && !tripRef.current.arrived) {
          const switchTo = shouldReroute(tripRef.current, r)
          if (switchTo) {
            chosenRef.current = switchTo.route.route_id
            setChosen(switchTo.route.route_id)
            rerouteRef.current?.(switchTo.route, switchTo.reason)
            showToastRef.current?.(`Rerouted: ${switchTo.reason}`, 5000)
            setFocusKey(Date.now())
          } else if (noSafeRoute(r)) {
            const now = Date.now()
            if (now - noSafeToastAt.current > 15000) {
              noSafeToastAt.current = now
              showToastRef.current?.('No safe route left. Stay put if you can and call 911.', 6000)
            }
          }
        } else if (chosenRef.current) {
          const pick = r?.options?.find((o) => o.id === chosenRef.current)
          if (pick && pick.status !== 'ok' && pick.status !== 'tight') {
            chosenRef.current = null
            setChosen(null)
          }
        }
        // Leave-by must never jump upward for the same pin: once we've told someone
        // "leave by T+X", a later poll can't push that deadline out while the fire grows.
        setRoute((prev) => ratchetLeaveBy(prev, r))
        // The countdown follows the route on screen: the picked card, else the best.
        const onScreen = withChoice(r, chosenRef.current).shown
        setDeadline((d) =>
          nextDeadline(d, {
            leaveBySim: r?.at_risk === false ? null : onScreen?.leave_by_sim_min,
            simTime: r?.sim_time,
            key: onScreen?.route_id ?? null,
          }),
        )
        setRouteError(null)
        // Traffic hint (contract v2.1): while driving, auto-take the faster path
        // so judges see Shepherd clearing jams; otherwise show the banner.
        try {
          const hintBody = await getTrafficHint(loc[1], loc[0], chosenRef.current ?? r?.best_route_id)
          const hint = hintBody?.hint
          if (hint?.saves_min >= 1) {
            setTrafficBanner(hint)
            const driving =
              evacuatingRef.current && tripRef.current && !tripRef.current.arrived
            const onHint =
              (chosenRef.current ?? tripRef.current?.route?.route_id) === hint.route_id
            if (driving && !onHint) {
              const pick =
                r?.options?.find((o) => o.id === hint.route_id) ||
                r?.options?.find(
                  (o) =>
                    o.shelter_id === hint.shelter_id &&
                    (o.status === 'ok' || o.status === 'tight'),
                )
              if (pick?.geometry) {
                const reason =
                  hint.message ||
                  `Traffic: faster route saves ${Math.round(hint.saves_min)} min`
                chosenRef.current = pick.id
                setChosen(pick.id)
                const flat = {
                  ...r,
                  ...pick,
                  route_id: pick.id,
                  best_route_id: r.best_route_id,
                  options: r.options,
                  rerouted: true,
                  reroute_reason: reason,
                }
                rerouteRef.current?.(flat, reason)
                showToastRef.current?.(`Rerouted: ${reason}`, 5000)
                setFocusKey(Date.now())
                trafficHintAt.current = Date.now()
              }
            } else if (Date.now() - trafficHintAt.current > 20000) {
              trafficHintAt.current = Date.now()
              showToastRef.current?.(hint.message, 5000)
            }
          } else {
            setTrafficBanner(null)
          }
        } catch {
          setTrafficBanner(null)
        }
      } catch (err) {
        if (stale()) return
        if (err.code !== 'no_route') {
          // Keep the last good route on the map; only show reconnect if we never had one.
          setRouteError('network')
          return
        }
        setRoute(null)
        setDeadline(null)
        // Contract only has error "no_route". Outside the demo box (or idle with
        // no fire) should not panic people into calling 911.
        const features = h.status === 'fulfilled' ? (h.value?.features ?? []) : []
        const fireOn = features.some(
          (f) => isCurrentCore(f) && (f.properties.kind === 'wildfire' || f.properties.kind === 'tornado'),
        )
        // v3 answers "everything is blocked" with a 200; its 404s are about place.
        const outOfArea = /demo area|within 300 m/i.test(err.message ?? '')
        setRouteError(fireOn && !outOfArea ? 'no_route' : 'out_of_area')
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
      setPlaceKey(lngLat.join(','))
      setRoute(null)
      setDeadline(null) // a new location gets a fresh countdown
      setRouteError(null)
      chosenRef.current = null
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

  // Priority residents: register this phone's id with an Alberta disability ID so the
  // dashboard marks it. Sent again on launch in case the backend restarted.
  const registerPriority = useCallback(
    async (details) => {
      setPrioritySending(true)
      try {
        await postPriority({ id: evacueeId(), ...details })
        setPriority(details)
        savePriority(details)
        setPriorityOpen(false)
        showToast(
          locationRef.current
            ? "You're registered as a priority resident. Responders can see you on their map."
            : "You're registered as a priority resident. Set your location so responders can see you.",
          5000,
        )
      } catch (err) {
        showToast(`Couldn't register: ${err.message || 'check your connection and try again.'}`, 5000)
      } finally {
        setPrioritySending(false)
      }
    },
    [showToast],
  )
  const removePriority = useCallback(async () => {
    setPrioritySending(true)
    try {
      await deletePriority(evacueeId())
      setPriority(null)
      savePriority(null)
      setPriorityOpen(false)
      showToast('Priority status removed.')
    } catch {
      showToast("Couldn't remove it. Check your connection and try again.")
    } finally {
      setPrioritySending(false)
    }
  }, [showToast])
  useEffect(() => {
    const saved = loadPriority()
    if (saved) postPriority({ id: evacueeId(), ...saved }).catch(() => {})
  }, [])

  // The route on screen: the card the user picked, or the backend's best.
  const { shown, lost } = withChoice(route, chosen)
  const shownRef = useRef(shown)
  useEffect(() => {
    shownRef.current = shown
  }, [shown])

  // "Start evacuating" (issue #56): a simulated drive along the chosen route, or the
  // phone's real GPS. Either way the dot moves without resetting the route choice.
  const [evacMode, setEvacMode] = useState('sim') // 'sim' | 'gps'
  const evacModeRef = useRef(evacMode)
  const beatNowRef = useRef(null)
  const moveTo = useCallback((lngLat) => {
    if (!lngLat) return
    locationRef.current = lngLat
    setLocation(lngLat)
    // A real GPS fix goes to the dashboard right away, not on the next 2 s tick.
    if (evacModeRef.current === 'gps') beatNowRef.current?.()
  }, [])
  const gpsFailed = useCallback((message) => showToast(message, 6000), [showToast])
  const { trip, start: startTrip, stop: stopTrip, reroute: rerouteTrip } = useEvacuation({
    clock,
    onMove: moveTo,
    onError: gpsFailed,
  })
  const evacuating = trip != null
  useEffect(() => {
    evacuatingRef.current = evacuating
    tripRef.current = trip
    rerouteRef.current = rerouteTrip
  }, [evacuating, trip, rerouteTrip])

  // While driving, the map follows the path on the trip (including mid-trip
  // reroutes), not a stale pre-trip recommendation.
  const driveRoute = trip
    ? {
        ...shown,
        ...trip.route,
        route_id: trip.route.route_id ?? trip.route.id,
        geometry: trip.route.geometry,
        shelter_id: trip.route.shelter_id,
        shelter_name: trip.route.shelter_name,
        eta_min: trip.route.eta_min,
        distance_km: trip.route.distance_km,
        rerouted: Boolean(trip.route.rerouted || trip.notice),
        reroute_reason: trip.route.reroute_reason ?? trip.notice,
      }
    : shown

  // Picking Real GPS moves the pin to the phone's actual location right away (and
  // routes from there), instead of waiting for Start evacuating. Simulated drive
  // keeps whatever location was tapped, for demos.
  const chooseEvacMode = useCallback(
    async (mode) => {
      evacModeRef.current = mode
      setEvacMode(mode)
      if (mode !== 'gps') return
      setToast(null)
      setLocating(true)
      const { lngLat, error } = await locateOnce()
      setLocating(false)
      // Ignore a late fix if the user switched back or already started a trip.
      if (evacModeRef.current !== 'gps' || evacuatingRef.current) return
      if (error) return showToast(error, 6000)
      showToast('Showing your real location.')
      setLocationAndRoute(lngLat)
    },
    [showToast, setLocationAndRoute],
  )

  // On launch, seed the pin from the phone's real location but keep Simulated drive
  // selected — they can tap the map (or a preset) to move, or switch to Real GPS.
  // If location is unavailable or denied, stay quiet: they can tap the map instead.
  useEffect(() => {
    let cancelled = false
    setLocating(true)
    locateOnce().then(({ lngLat }) => {
      if (!cancelled) setLocating(false)
      // Skip if the user already tapped the map while we waited.
      if (cancelled || !lngLat || locationRef.current) return
      evacModeRef.current = 'sim'
      setEvacMode('sim')
      setAutoLocation(lngLat) // keeps the route panel collapsed for this fix
      setLocationAndRoute(lngLat)
    })
    return () => {
      cancelled = true
    }
  }, [setLocationAndRoute])

  // Tapping the map drops a pending pin and asks before moving the person there
  // (a stray tap while panning shouldn't reroute them). Tapping again moves the
  // pending pin. A confirmed tap stays on Simulated drive; picking Real GPS jumps
  // back to the phone's live location.
  const [pendingTap, setPendingTap] = useState(null) // [lon, lat] awaiting confirmation
  const tapMap = useCallback(
    (lngLat) => {
      // While placing a report, a tap moves the report pin there instead.
      if (reportStep === 'place') {
        setReportAt(lngLat)
        return
      }
      setPendingTap(lngLat)
    },
    [reportStep],
  )

  // Report a hazard anywhere: Report drops a pin in the middle of the map, the person
  // drags it (or taps the map) to the incident and drops it, then the sheet takes the
  // type and a short message for responders. Everyone's map shows it on the next poll.
  const startReport = useCallback(() => {
    setPendingTap(null)
    setReportAt(mapCenterRef.current)
    setReportStep('place')
  }, [])
  const cancelReport = useCallback(() => {
    setReportStep(null)
    setReportAt(null)
  }, [])
  const sendHazardReport = useCallback(
    async ({ kind, note }) => {
      if (!reportAt) return
      setSending(true)
      try {
        await postReport({ kind, lat: reportAt[1], lon: reportAt[0], note })
        cancelReport()
        showToast('Report sent. Everyone using Shepherd can see it on their map.')
        getReports()
          .then(setReports)
          .catch(() => {})
      } catch {
        showToast("Couldn't send. Check your connection and try again.")
      } finally {
        setSending(false)
      }
    },
    [reportAt, cancelReport, showToast],
  )
  const confirmTap = useCallback(() => {
    if (!pendingTap) return
    evacModeRef.current = 'sim'
    setEvacMode('sim')
    setLocating(false) // a confirmed tap wins over a GPS fix still on its way
    setPendingTap(null)
    setLocationAndRoute(pendingTap)
  }, [pendingTap, setLocationAndRoute])
  const cancelTap = useCallback(() => setPendingTap(null), [])

  // "Need help" asks once before sending an SOS, so a stray tap doesn't alert
  // responders. It replaces any tapped location still waiting for confirmation.
  const [confirmHelp, setConfirmHelp] = useState(false)
  const askHelp = useCallback(() => {
    setPendingTap(null)
    cancelReport()
    setConfirmHelp(true)
  }, [cancelReport])
  const sendHelp = useCallback(() => {
    setConfirmHelp(false)
    sendReport('sos')
  }, [sendReport])
  // Starting a trip locks the location, so drop any unconfirmed tap.
  useEffect(() => {
    if (evacuating) setPendingTap(null)
  }, [evacuating])

  // Heartbeat to POST /evacuees every ~2 s once the user has set a location (by tapping
  // the map, a preset, or Need help) and while evacuating (simulated or GPS), so the
  // dashboard marks where they are. The backend drops a phone after 30 s without a
  // beat, so it keeps beating while a location is set.
  const readHeartbeat = useCallback(() => {
    const loc = locationRef.current
    if (!loc) return null
    const driving = tripRef.current?.route
    const r = driving ?? shownRef.current
    const coords = r?.geometry?.coordinates
    return {
      lat: loc[1],
      lon: loc[0],
      route_id: r?.route_id ?? r?.id ?? null,
      route_status: r?.status ?? null,
      shelter_id: r?.shelter_id ?? null,
      // So the dashboard can draw this phone's path and show live mid-trip reroutes.
      route_coords: Array.isArray(coords) && coords.length >= 2 ? coords : null,
    }
  }, [])
  const beatNow = useHeartbeat({
    active: evacuating || location != null,
    everyMs: POLL_MS,
    read: readHeartbeat,
    send: postEvacuee,
  })
  useEffect(() => {
    beatNowRef.current = beatNow
  }, [beatNow])

  // With Real GPS picked, the pin follows the phone even before Start evacuating
  // (a trip runs its own watch). Waits for the first fix so it can't race it.
  const following = evacMode === 'gps' && !evacuating && location != null && !locating
  useEffect(() => {
    followingRef.current = following
  }, [following])
  useFollowGps({ active: following, onFix: moveTo, onError: gpsFailed })

  // Keep the screen on during a trip: a locked screen stops GPS in the browser.
  useWakeLock(evacuating)

  // During a wildfire the evacuation card (leave-by countdown) takes the banner's place.
  const wildfire =
    route?.leave_by_sim_min != null ||
    (hazards?.features ?? []).some(
      (f) => isCurrentCore(f) && (f.properties.kind === 'wildfire' || f.properties.kind === 'tornado'),
    )

  const detailProps = {
    location,
    route: driveRoute,
    lost,
    routeError,
    shelters,
    onChoose: (routeId) => {
      chosenRef.current = routeId
      setChosen(routeId)
      setFocusKey(Date.now()) // frame the newly picked route
    },
    trip,
    evacMode,
    onEvacMode: chooseEvacMode,
    onStartEvacuating: () => {
      const id = shown?.route_id ?? shown?.best_route_id
      if (id) {
        chosenRef.current = id
        setChosen(id)
      }
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
            route={driveRoute}
            location={location}
            pending={pendingTap}
            reports={reports}
            reportPin={reportStep ? reportAt : null}
            reportStep={reportStep}
            onReportPinMove={setReportAt}
            onTap={evacuating && !reportStep ? undefined : tapMap}
            onViewChange={onViewChange}
            focusKey={focusKey}
            framePadding={framePadding}
          />
        )}
        alert={
          <>
            {trafficBanner && (
              <div className="alert alert-advisory traffic-faster" role="status">
                <div className="alert-text">
                  <strong>{trafficBanner.message}</strong>
                  <span className="num">Switch routes to skip the jam.</span>
                </div>
              </div>
            )}
            {wildfire ? (
              <EvacCard
                location={location}
                route={driveRoute}
                routeError={routeError}
                near={location ? nearestHazard(location, hazards) : null}
                deadline={deadline}
                trip={trip}
              />
            ) : (
              <AlertBanner hazards={hazards} location={location} notifications={notifications} />
            )}
          </>
        }
        details={<RouteDetails {...detailProps} />}
        more={
          <RouteMore route={driveRoute} shelters={shelters} trip={trip} evacMode={evacMode} deadline={deadline} />
        }
        mapKey={<MapKey hazards={hazards} shelters={shelters} route={driveRoute} location={location} reports={reports} />}
        areaName={areaName}
        notifications={notifications}
        location={location}
        placeKey={placeKey}
        autoLocation={autoLocation}
        route={driveRoute}
        routeError={routeError}
        trip={trip}
        version={SHEPHERD_VERSION}
        actions={{
          report: startReport,
          priority: () => setPriorityOpen(true),
          isPriority: priority != null,
          help: askHelp,
          canReport: !sending,
          sending,
        }}
      />

      {confirmHelp ? (
        <div className="confirm-box" role="alertdialog" aria-labelledby="help-title" aria-describedby="help-desc">
          <strong id="help-title">Send a help request?</strong>
          <span id="help-desc">
            {location
              ? 'Responders will see your location and come to help.'
              : "Shepherd will use your phone's location so responders can find you."}{' '}
            If you are in danger, also call 911.
          </span>
          <div className="confirm-actions">
            <button type="button" className="btn-outline" onClick={() => setConfirmHelp(false)}>
              Cancel
            </button>
            <button type="button" className="btn-help" onClick={sendHelp} autoFocus>
              Send request
            </button>
          </div>
        </div>
      ) : reportStep === 'place' ? (
        <div className="confirm-box" role="dialog" aria-labelledby="place-title" aria-describedby="place-desc">
          <strong id="place-title">Where is the hazard?</strong>
          <span id="place-desc">Drag the pin to the spot, or tap the map.</span>
          <div className="confirm-actions">
            <button type="button" className="btn-outline" onClick={cancelReport}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={!reportAt} onClick={() => setReportStep('details')}>
              Drop pin here
            </button>
          </div>
        </div>
      ) : pendingTap ? (
        <div className="confirm-box" role="dialog" aria-labelledby="confirm-title">
          <strong id="confirm-title">Set your location here?</strong>
          <span>Shepherd will find routes from this spot.</span>
          <div className="confirm-actions">
            <button type="button" className="btn-outline" onClick={cancelTap}>
              Cancel
            </button>
            <button type="button" className="btn-primary" onClick={confirmTap} autoFocus>
              Set location
            </button>
          </div>
        </div>
      ) : toast ? (
        <div className="toast" role="status">
          {toast}
        </div>
      ) : (
        locating && (
          <div className="toast" role="status">
            Finding your location
            <span className="loading-dots" aria-hidden="true">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
          </div>
        )
      )}

      {priorityOpen && (
        <PrioritySheet
          registered={priority}
          sending={prioritySending}
          onSubmit={registerPriority}
          onRemove={removePriority}
          onClose={() => setPriorityOpen(false)}
        />
      )}

      {reportStep === 'details' && (
        <ReportSheet
          sending={sending}
          onClose={cancelReport}
          onMovePin={() => setReportStep('place')}
          onSubmit={sendHazardReport}
        />
      )}
    </div>
  )
}
