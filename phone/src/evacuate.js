import { useCallback, useEffect, useRef, useState } from 'react'
import { distanceKm } from './geo.js'
import { cueForProgress, routeCoords, turnsAlong } from './turns.js'

// Issue #56: "Start evacuating" either drives a simulated dot along the chosen
// route (in-room demo) or follows the phone's real GPS (hallway / outdoor video).

// The backend advances `speed` sim minutes every 2 real seconds, so the simulated
// drive covers the route's ETA on the same clock as the fire.
const TICK_MS = 2000
const FRAME_MS = 250
// Pause the simulated drive so a turn popup can be read (Google Maps-style cue).
const TURN_PAUSE_MS = 1800
const TURN_ANNOUNCE_M = 120

// ---------- route geometry ----------

function legs(coords) {
  const out = []
  let total = 0
  for (let i = 1; i < coords.length; i++) {
    const km = distanceKm(coords[i - 1], coords[i])
    out.push({ from: coords[i - 1], to: coords[i], start: total, km })
    total += km
  }
  return { legs: out, total }
}

// [lon, lat] at `fraction` (0–1) of the way along a LineString's coordinates.
function pointAlong(coords, fraction) {
  if (!coords?.length) return null
  const { legs: ls, total } = legs(coords)
  if (total === 0 || fraction <= 0) return coords[0]
  if (fraction >= 1) return coords[coords.length - 1]
  const target = total * fraction
  const leg = ls.find((l) => target <= l.start + l.km) ?? ls[ls.length - 1]
  const t = leg.km === 0 ? 0 : (target - leg.start) / leg.km
  return [leg.from[0] + (leg.to[0] - leg.from[0]) * t, leg.from[1] + (leg.to[1] - leg.from[1]) * t]
}

export const routeLengthKm = (coords) => (coords?.length ? legs(coords).total : 0)

// ---------- evacuee id ----------

// One id per phone (issue #57), so heartbeats upsert one dot on the dashboard and a
// refresh keeps the same dot. Kept in localStorage; if storage is blocked it lasts
// for this page load. `ev_` prefix per the contract's id convention.
const ID_KEY = 'shepherd.evacueeId'
const ID_PATTERN = /^ev_[0-9a-f]{12}$/
let memoryId = null

function newId() {
  const bytes = new Uint8Array(6)
  // getRandomValues works on plain http too (randomUUID needs https).
  if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes)
  else bytes.forEach((_, i) => (bytes[i] = Math.floor(Math.random() * 256)))
  return `ev_${[...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')}`
}

export function evacueeId() {
  try {
    let id = localStorage.getItem(ID_KEY)
    if (!ID_PATTERN.test(id ?? '')) {
      id = newId()
      localStorage.setItem(ID_KEY, id)
    }
    return id
  } catch {
    memoryId ??= newId()
    return memoryId
  }
}

// ---------- heartbeat ----------

// POST /evacuees every `everyMs` while `active`: the phone's id, position and chosen
// route. Skips a beat while the previous one is still in flight (slow networks), and
// beats again as soon as the page is visible (browsers throttle timers in hidden tabs).
// `read()` returns { lat, lon, route_id, route_status, shelter_id } or null.
// Returns `beatNow()`: call it on a fresh GPS fix to send it straight away instead of
// waiting up to `everyMs` (sends at most once per `minGapMs`).
export function useHeartbeat({ active, everyMs, read, send, minGapMs = 1000 }) {
  const readRef = useRef(read)
  const sendRef = useRef(send)
  const beatRef = useRef(null)
  useEffect(() => {
    readRef.current = read
    sendRef.current = send
  }, [read, send])

  useEffect(() => {
    if (!active) return
    const id = evacueeId()
    let inFlight = false
    let lastSent = 0
    const beat = async ({ throttle = false } = {}) => {
      const now = Date.now()
      if (inFlight || (throttle && now - lastSent < minGapMs)) return
      const body = readRef.current?.()
      if (!body) return
      inFlight = true
      lastSent = now
      try {
        await sendRef.current({ id, ...body })
      } catch {
        // a missed (or timed out) beat is fine; the next one follows shortly
      } finally {
        inFlight = false
      }
    }
    beatRef.current = () => beat({ throttle: true })
    const onVisible = () => document.visibilityState === 'visible' && beat()
    beat()
    const timer = setInterval(() => beat({ throttle: true }), everyMs)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      beatRef.current = null
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [active, everyMs, minGapMs])

  return useCallback(() => beatRef.current?.(), [])
}

// ---------- screen wake lock ----------

// Keep the screen on while `active` (a trip in progress). Browsers stop GPS and slow
// timers once the screen locks, which froze the dot on the dashboard mid-drive. The
// lock drops whenever the page is hidden, so take it again when it comes back.
// Silently does nothing where unsupported (older Safari, plain http).
export function useWakeLock(active) {
  useEffect(() => {
    if (!active || !navigator.wakeLock) return
    let lock = null
    let cancelled = false
    const acquire = async () => {
      if (document.visibilityState !== 'visible' || (lock && !lock.released)) return
      try {
        const next = await navigator.wakeLock.request('screen')
        if (cancelled) next.release().catch(() => {})
        else lock = next
      } catch {
        // denied (battery saver, not visible): nothing to do
      }
    }
    acquire()
    document.addEventListener('visibilitychange', acquire)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', acquire)
      lock?.release().catch(() => {})
    }
  }, [active])
}

// ---------- GPS ----------

function gpsError(err) {
  if (!window.isSecureContext) return 'Real GPS needs the https link. Open Shepherd over https, or use Simulated drive.'
  if (!navigator.geolocation) return "This browser can't share your location. Use Simulated drive."
  if (err?.code === 1) return 'Location permission was denied. Allow it in your browser settings, or use Simulated drive.'
  return "Couldn't get your location. Check that location is on, or use Simulated drive."
}

// Follow the device's GPS while `active` (Real GPS picked, no trip running; a trip
// runs its own watch). Before this, the pin only took one fix when Real GPS was
// picked, so a phone driving around without pressing Start evacuating kept sending
// the same spot. onFix([lon, lat]) per fix; onError(message) if permission is denied.
export function useFollowGps({ active, onFix, onError }) {
  const fixRef = useRef(onFix)
  const errorRef = useRef(onError)
  useEffect(() => {
    fixRef.current = onFix
    errorRef.current = onError
  }, [onFix, onError])

  useEffect(() => {
    if (!active || !window.isSecureContext || !navigator.geolocation) return
    const id = navigator.geolocation.watchPosition(
      (p) => fixRef.current?.([p.coords.longitude, p.coords.latitude]),
      (err) => {
        // Weak signal: keep the last position quietly; the watch keeps trying.
        if (err?.code === 1) errorRef.current?.(gpsError(err))
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 },
    )
    return () => navigator.geolocation.clearWatch(id)
  }, [active])
}

// One fresh fix for "Real GPS" being picked: resolves { lngLat: [lon, lat] } or
// { error: message } so the pin can jump to where the phone actually is.
export function locateOnce() {
  return new Promise((resolve) => {
    if (!window.isSecureContext || !navigator.geolocation) return resolve({ error: gpsError() })
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lngLat: [p.coords.longitude, p.coords.latitude] }),
      (err) => resolve({ error: gpsError(err) }),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 5000 },
    )
  })
}

// ---------- the hook ----------

// trip: null | { mode, route, arrived, fraction, turnCue, coords, turns, totalKm,
//                notice, driveKey }
// `route` is the path currently being driven (updated on mid-trip reroute).
// `turnCue` is the brief Google Maps-style popup while approaching a corner.
// `notice` is a short "Rerouted: …" line after a mid-trip switch.
// onMove([lon, lat]) is called with every new position; onError(message) when GPS fails.
export function useEvacuation({ clock, onMove, onError }) {
  const [trip, setTrip] = useState(null)
  const tripRef = useRef(trip)
  const clockRef = useRef(clock)
  const moveRef = useRef(onMove)
  const errorRef = useRef(onError)
  const announcedRef = useRef(new Set())
  const pauseUntilRef = useRef(0)
  const drivenMinRef = useRef(0)

  useEffect(() => {
    tripRef.current = trip
    clockRef.current = clock
    moveRef.current = onMove
    errorRef.current = onError
  }, [trip, clock, onMove, onError])

  const stop = useCallback(() => {
    announcedRef.current = new Set()
    pauseUntilRef.current = 0
    drivenMinRef.current = 0
    setTrip(null)
  }, [])

  const beginDrive = useCallback((mode, route, notice = null) => {
    const coords = routeCoords(route?.geometry)
    const turns = turnsAlong(route?.geometry)
    const totalKm = routeLengthKm(coords)
    announcedRef.current = new Set()
    pauseUntilRef.current = 0
    drivenMinRef.current = 0
    return {
      mode,
      route: {
        ...route,
        route_id: route.route_id ?? route.id,
        ...(notice
          ? { rerouted: true, reroute_reason: notice }
          : { rerouted: false, reroute_reason: null }),
      },
      arrived: false,
      fraction: 0,
      turnCue: null,
      coords,
      turns,
      totalKm,
      notice,
      driveKey: Date.now(),
    }
  }, [])

  const start = useCallback(
    (mode, route) => {
      if (mode === 'gps' && (!window.isSecureContext || !navigator.geolocation)) {
        errorRef.current?.(gpsError())
        return
      }
      if (!route?.geometry) return
      setTrip(beginDrive(mode, route))
    },
    [beginDrive],
  )

  // Swap onto a new path from the current pin (fire moved / shelter went unsafe).
  const reroute = useCallback(
    (route, reason) => {
      if (!route?.geometry) return
      setTrip((prev) => {
        if (!prev || prev.arrived) return prev
        return beginDrive(prev.mode, route, reason)
      })
    },
    [beginDrive],
  )

  // Simulated drive: advance along the route on the sim clock (frozen while paused
  // by the dashboard clock, or briefly when a turn cue is on screen).
  // `driveKey` restarts the clock when we mid-trip reroute onto a new path.
  const simulating = trip?.mode === 'sim' && !trip.arrived
  const driveKey = trip?.driveKey
  useEffect(() => {
    if (!simulating) return
    let last = Date.now()
    drivenMinRef.current = 0
    const id = setInterval(() => {
      const t = tripRef.current
      if (t?.mode !== 'sim') return
      const now = Date.now()
      const c = clockRef.current
      const holding = now < pauseUntilRef.current
      const coords = t.coords?.length ? t.coords : routeCoords(t.route.geometry)
      const totalKm = t.totalKm || routeLengthKm(coords)
      const eta = Math.max(t.route.eta_min || 1, 1)

      // Show the cue and hold before rolling past the corner.
      let fraction = Math.min(drivenMinRef.current / eta, 1)
      let kmAlong = totalKm * fraction
      const cue = cueForProgress(t.turns || [], kmAlong, announcedRef.current, TURN_ANNOUNCE_M)
      let turnCue = holding ? t.turnCue : null
      if (cue && !holding) {
        announcedRef.current.add(cue.id)
        pauseUntilRef.current = now + TURN_PAUSE_MS
        turnCue = cue
      } else if (!holding) {
        turnCue = null
        if (c?.state !== 'paused') {
          drivenMinRef.current += ((now - last) / TICK_MS) * (c?.speed || 1)
        }
        fraction = Math.min(drivenMinRef.current / eta, 1)
        kmAlong = totalKm * fraction
      }
      last = now
      moveRef.current?.(pointAlong(coords, fraction))

      setTrip((prev) =>
        prev?.mode === 'sim'
          ? { ...prev, fraction, arrived: fraction >= 1, turnCue: fraction >= 1 ? null : turnCue }
          : prev,
      )
    }, FRAME_MS)
    return () => clearInterval(id)
  }, [simulating, driveKey])

  // Real GPS: follow the device until stopped. Show turn cues without pausing.
  const following = trip?.mode === 'gps'
  useEffect(() => {
    if (!following) return
    let warned = false
    const id = navigator.geolocation.watchPosition(
      (p) => {
        warned = false
        const here = [p.coords.longitude, p.coords.latitude]
        moveRef.current?.(here)
        setTrip((prev) => {
          if (prev?.mode !== 'gps') return prev
          const coords = prev.coords?.length ? prev.coords : routeCoords(prev.route.geometry)
          if (!coords.length) return prev
          // Nearest point on the route → progress along it.
          let bestI = 0
          let bestD = Infinity
          for (let i = 0; i < coords.length; i++) {
            const d = distanceKm(here, coords[i])
            if (d < bestD) {
              bestD = d
              bestI = i
            }
          }
          let kmAlong = 0
          for (let i = 1; i <= bestI; i++) kmAlong += distanceKm(coords[i - 1], coords[i])
          const totalKm = prev.totalKm || routeLengthKm(coords)
          const fraction = totalKm > 0 ? Math.min(kmAlong / totalKm, 1) : 0
          const cue = cueForProgress(prev.turns || [], kmAlong, announcedRef.current, TURN_ANNOUNCE_M)
          let turnCue = prev.turnCue
          if (cue) {
            announcedRef.current.add(cue.id)
            turnCue = cue
            // Clear after a beat so the popup doesn't stick forever on GPS.
            setTimeout(() => {
              setTrip((cur) => (cur?.turnCue?.id === cue.id ? { ...cur, turnCue: null } : cur))
            }, TURN_PAUSE_MS)
          }
          return { ...prev, fraction, arrived: fraction >= 0.98, turnCue }
        })
      },
      (err) => {
        if (err?.code === 1) {
          errorRef.current?.(gpsError(err))
          setTrip(null)
        } else if (!warned) {
          warned = true
          errorRef.current?.('Weak GPS signal. Still trying… your last position is shown.')
        }
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 },
    )
    return () => navigator.geolocation.clearWatch(id)
  }, [following])

  return { trip, start, stop, reroute }
}
