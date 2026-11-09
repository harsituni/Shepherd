// The sim clock, for the simulated drive (src/evacuate.js). The backend advances the
// sim by `speed` minutes every 2 real seconds (backend/api/main.py `_sim_loop`).
// The leave-by countdown does NOT use it: it runs on this phone's clock (leaveBy.js).

// Clock snapshot from a poll. Keeps the previous object (and its `at` stamp) when
// nothing changed, so `at` marks when this sim minute was first seen.
export function nextClock(prev, { sim_time, speed = 1, state = 'running' }) {
  if (sim_time == null) return prev
  if (prev && prev.sim_time === sim_time && prev.speed === speed && prev.state === state) return prev
  return { sim_time, speed, state, at: Date.now() }
}

// 5.7 sim minutes → "5:42".
export function formatMinSec(minutes) {
  const total = Math.max(0, Math.floor(minutes * 60))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
