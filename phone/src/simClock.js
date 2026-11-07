import { useEffect, useState } from 'react'

// The backend advances the sim by `speed` minutes every 2 real seconds
// (backend/api/main.py `_sim_loop`), so one sim minute is 2000 / speed ms.
const TICK_MS = 2000
const FRAME_MS = 250

// Clock snapshot from a poll. Keeps the previous object (and its `at` stamp) when
// nothing changed, so `at` marks when this sim minute was first seen and the
// interpolation below never runs backwards.
export function nextClock(prev, { sim_time, speed = 1, state = 'running' }) {
  if (sim_time == null) return prev
  if (prev && prev.sim_time === sim_time && prev.speed === speed && prev.state === state) return prev
  return { sim_time, speed, state, at: Date.now() }
}

// Current sim time in fractional minutes, ticking smoothly between polls.
// Returns null until there is a sim time to work from.
export function useSimNow(clock) {
  const [now, setNow] = useState(() => Date.now())
  const running = clock?.state === 'running'

  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(Date.now()), FRAME_MS)
    return () => clearInterval(id)
  }, [running])

  if (clock?.sim_time == null) return null
  if (!running) return clock.sim_time
  // At most one backend tick ahead of the last value seen.
  const ahead = Math.min(Math.max(now - clock.at, 0) / TICK_MS, 1)
  return clock.sim_time + ahead * (clock.speed || 1)
}

// 5.7 sim minutes → "5:42".
export function formatMinSec(minutes) {
  const total = Math.max(0, Math.floor(minutes * 60))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
