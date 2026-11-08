import { useEffect, useRef, useState } from 'react'

// Issue #58: "if my route goes bad". The phone already re-fetches GET /route every
// 2 s (from the moving dot while evacuating). This watches the one route the user is
// relying on (the card they picked, the route they're driving, or the recommended
// route they were shown) and raises an alert when it gets worse:
//   ok -> tight, anything -> blocked, or the shelter drops out of the options.
// A 404 no_route counts as every route blocked. Network errors change nothing here
// (the phone says it can't check instead, see `staleFor`).

const RANK = { ok: 0, tight: 1, blocked: 2, gone: 2 }

// Status of `shelterId` in a normalized /route body: 'ok' | 'tight' | 'blocked' | 'gone'.
export function statusOf(route, routeError, shelterId) {
  if (routeError === 'no_route') return 'blocked'
  if (!route?.options) return null // v1 backend or no answer yet: nothing to compare
  const o = route.options.find((x) => x.shelter_id === shelterId)
  return o ? o.status : 'gone'
}

// The best usable option other than `shelterId`, to offer as the way out.
export function alternative(route, shelterId) {
  const usable = (route?.options ?? []).filter((o) => o.status !== 'blocked' && o.shelter_id !== shelterId)
  if (!usable.length) return null
  return usable.find((o) => o.id === route.best_route_id) ?? usable.find((o) => o.status === 'ok') ?? usable[0]
}

// Pure step for the watcher, so it can be tested without React.
// prev: { key, shelterId, shelterName, status } | null
// Returns { watch, alert } where alert is null or { shelterId, shelterName, from, to, reason }.
export function step(prev, { key, route, routeError, shownShelterId, shownShelterName }) {
  // New location, new pick or a new trip: start watching whatever is shown now.
  if (!prev || prev.key !== key || !prev.shelterId) {
    if (!shownShelterId) return { watch: { key, shelterId: null }, alert: null }
    const status = statusOf(route, routeError, shownShelterId)
    return { watch: { key, shelterId: shownShelterId, shelterName: shownShelterName, status }, alert: null }
  }
  const status = statusOf(route, routeError, prev.shelterId)
  if (status == null) return { watch: prev, alert: null }
  const watch = { ...prev, status }
  if (prev.status != null && RANK[status] > RANK[prev.status]) {
    const o = route?.options?.find((x) => x.shelter_id === prev.shelterId)
    return {
      watch,
      alert: { shelterId: prev.shelterId, shelterName: prev.shelterName, from: prev.status, to: status, reason: o?.reason ?? null },
    }
  }
  return { watch, alert: null }
}

// React wrapper. `key` changes whenever the user picks a new baseline (new pin,
// picked card, started a trip); `route` is the latest normalized /route body.
// Returns { alert, dismiss, improved } where alert stays up until dismissed, a new
// baseline is chosen, or the watched route recovers to (or below) its old status.
export function useRouteWatch({ key, route, routeError, shownShelterId, shownShelterName }) {
  const watchRef = useRef(null)
  const [alert, setAlert] = useState(null)
  const [raised, setRaised] = useState(0) // counts alerts, so the UI can react to each new one

  useEffect(() => {
    const prevKey = watchRef.current?.key
    const { watch, alert: fresh } = step(watchRef.current, { key, route, routeError, shownShelterId, shownShelterName })
    watchRef.current = watch
    if (prevKey !== key) setAlert(null)
    if (fresh) {
      setAlert(fresh)
      setRaised((n) => n + 1)
      try {
        navigator.vibrate?.([200, 100, 200])
      } catch {
        // vibration is a nice-to-have
      }
    } else if (watch.status != null) {
      // Recovered (e.g. the wind swung back): the alert no longer applies.
      setAlert((a) => (a && a.shelterId === watch.shelterId && RANK[watch.status] < RANK[a.to] ? null : a))
    }
  }, [key, route, routeError, shownShelterId, shownShelterName])

  return { alert, raised, dismiss: () => setAlert(null) }
}

// While route checks are failing (`active`): { seconds } since the last good check
// (seconds is null if there never was one), ticking once a second, once it has been
// failing for more than `afterMs`. null otherwise.
export function useStaleFor(lastOkAt, active, afterMs) {
  // { since, now } for the current run of failures, ticked once a second.
  const [tick, setTick] = useState(null)
  useEffect(() => {
    if (!active) return
    const since = Date.now()
    const id = setInterval(() => setTick({ since, now: Date.now() }), 1000)
    return () => {
      clearInterval(id)
      setTick(null)
    }
  }, [active])
  if (!active || !tick || tick.now - tick.since < afterMs) return null
  return { seconds: lastOkAt == null ? null : Math.round((tick.now - lastOkAt) / 1000) }
}
