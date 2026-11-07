import { useCallback, useEffect, useRef, useState } from 'react'
import { distanceKm } from './geo.js'

// Issue #56: "Start evacuating" either drives a simulated dot along the chosen
// route (in-room demo) or follows the phone's real GPS (hallway / outdoor video).

// The backend advances `speed` sim minutes every 2 real seconds, so the simulated
// drive covers the route's ETA on the same clock as the leave-by countdown.
const TICK_MS = 2000
const FRAME_MS = 250

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
export function pointAlong(coords, fraction) {
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

// One id per phone, so heartbeats upsert one dot on the dashboard. Kept in
// localStorage when available; otherwise it lasts for this page load.
let memoryId = null
export function evacueeId() {
  const make = () => `ev_${Math.random().toString(36).slice(2, 8)}`
  try {
    let id = localStorage.getItem('shepherd.evacueeId')
    if (!id) {
      id = make()
      localStorage.setItem('shepherd.evacueeId', id)
    }
    return id
  } catch {
    memoryId ??= make()
    return memoryId
  }
}

// ---------- GPS ----------

function gpsError(err) {
  if (!window.isSecureContext) return 'Real GPS needs the https link. Open Shepherd over https, or use Simulated drive.'
  if (!navigator.geolocation) return "This browser can't share your location. Use Simulated drive."
  if (err?.code === 1) return 'Location permission was denied. Allow it in your browser settings, or use Simulated drive.'
  return "Couldn't get your location. Check that location is on, or use Simulated drive."
}

// ---------- the hook ----------

// trip: null | { mode: 'sim' | 'gps', route, arrived, fraction }
// `route` is a snapshot of the chosen option when Start was pressed.
// onMove([lon, lat]) is called with every new position; onError(message) when GPS fails.
export function useEvacuation({ clock, onMove, onError }) {
  const [trip, setTrip] = useState(null)
  const tripRef = useRef(trip)
  const clockRef = useRef(clock)
  const moveRef = useRef(onMove)
  const errorRef = useRef(onError)

  useEffect(() => {
    tripRef.current = trip
    clockRef.current = clock
    moveRef.current = onMove
    errorRef.current = onError
  }, [trip, clock, onMove, onError])

  const stop = useCallback(() => setTrip(null), [])

  const start = useCallback((mode, route) => {
    if (mode === 'gps' && (!window.isSecureContext || !navigator.geolocation)) {
      errorRef.current?.(gpsError())
      return
    }
    setTrip({ mode, route, arrived: false, fraction: 0 })
  }, [])

  // Simulated drive: advance along the route on the sim clock (frozen while paused).
  const simulating = trip?.mode === 'sim' && !trip.arrived
  useEffect(() => {
    if (!simulating) return
    let last = Date.now()
    let drivenMin = 0
    const id = setInterval(() => {
      const t = tripRef.current
      if (t?.mode !== 'sim') return
      const now = Date.now()
      const c = clockRef.current
      if (c?.state !== 'paused') drivenMin += ((now - last) / TICK_MS) * (c?.speed || 1)
      last = now
      const fraction = Math.min(drivenMin / Math.max(t.route.eta_min || 1, 1), 1)
      moveRef.current?.(pointAlong(t.route.geometry.coordinates, fraction))
      setTrip((prev) => (prev?.mode === 'sim' ? { ...prev, fraction, arrived: fraction >= 1 } : prev))
    }, FRAME_MS)
    return () => clearInterval(id)
  }, [simulating])

  // Real GPS: follow the device until stopped.
  // Only a denied permission ends the trip. "Unavailable" and timeouts are normal
  // blips while the fix changes (indoors, tunnels), so keep watching and say so once.
  const following = trip?.mode === 'gps'
  useEffect(() => {
    if (!following) return
    let warned = false
    const id = navigator.geolocation.watchPosition(
      (p) => {
        warned = false
        moveRef.current?.([p.coords.longitude, p.coords.latitude])
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

  return { trip, start, stop }
}
