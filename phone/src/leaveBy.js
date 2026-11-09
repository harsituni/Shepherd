import { useEffect, useState } from 'react'

// "Leave within" runs on this phone's clock, not the simulation's.
//
// /route sends leave_by_sim_min, a sim minute. The first time one shows up, the gap
// (leave_by_sim_min - sim_time) becomes a real deadline on this phone, now + that many
// real minutes, and it counts down one second per second whatever the sim speed or
// pause. Later answers only move it earlier, and only by as much as the backend's own
// deadline moved earlier (the forecast got worse, or the route on screen has an
// earlier one): the sim racing ahead never shortens it, and nothing moves it later.
// An answer without a leave-by keeps it; `clear` (not at risk) drops it. A restarted
// sim starts over; App clears it when the location is set again.
export function nextDeadline(prev, { leaveBySim, simTime, clear = false, nowMs = Date.now() }) {
  if (simTime == null) return prev
  const restarted = prev != null && simTime < prev.simTime
  if (clear || (leaveBySim == null && (restarted || !prev))) return null
  if (leaveBySim == null) return { ...prev, simTime }
  if (!prev || restarted) return { leaveBySim, simTime, atMs: nowMs + (leaveBySim - simTime) * 60_000 }
  if (leaveBySim < prev.leaveBySim) {
    return { leaveBySim, simTime, atMs: prev.atMs - (prev.leaveBySim - leaveBySim) * 60_000 }
  }
  return prev.simTime === simTime ? prev : { ...prev, simTime }
}

// Date.now(), re-read every second while `active`.
export function useNow(active = true) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

// 3:42 PM on this phone's clock.
export const clockTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
