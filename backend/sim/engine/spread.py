"""Fire arrival times by time-dependent minimum travel time (Dijkstra on the grid).

Each burning cell spreads to its 16 neighbours (8 adjacent + 8 knight moves,
which cuts the octagonal distortion of 8-neighbour grids) at the elliptical
directional rate for that bearing. The rate uses the weather at the source
cell's arrival time, so a fire that arrives earlier never ends up arriving
later and Dijkstra stays correct with time-varying wind.

The per-minute, per-neighbour travel times are precomputed from the weather
table, so the inner loop is only lookups and additions.
"""

import heapq
import math

import numpy as np

from backend.sim.engine import fbp

# (d_row, d_col); north = -d_row, east = +d_col.
NEIGHBOURS_16 = (
    (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1),
    (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1),
)
MIN_RATE_M_PER_MIN = 1e-6


def neighbour_bearing(dr, dc):
    return math.degrees(math.atan2(dc, -dr)) % 360


def jumped_cells(dr, dc):
    """The two cells a knight move passes between; () for adjacent moves."""
    if abs(dc) == 2:
        return (0, dc // 2), (dr, dc // 2)
    if abs(dr) == 2:
        return (dr // 2, 0), (dr // 2, dc)
    return ()


def neighbour_rates(table) -> np.ndarray:
    """Spread rate (m/min) toward each neighbour, shape (len(table), 16)."""
    bearings = np.array([neighbour_bearing(dr, dc) for dr, dc in NEIGHBOURS_16])
    theta = np.radians(bearings[None, :] - table.spread_bearing_deg[:, None])
    return fbp.directional_ros(
        table.ros[:, None], table.bros[:, None], table.fros[:, None], theta
    )


def compute_arrival(seed_mask, burnable, weather_table, cell_m, horizon_min) -> np.ndarray:
    """Minutes after t0 when fire reaches each cell; NaN if not within horizon_min."""
    rows, cols = seed_mask.shape
    dist_m = np.array([math.hypot(dr, dc) * cell_m for dr, dc in NEIGHBOURS_16])
    rates = neighbour_rates(weather_table)
    with np.errstate(divide="ignore"):
        travel = np.where(rates > MIN_RATE_M_PER_MIN, dist_m / rates, math.inf)
    travel_by_minute = travel.tolist()
    last_minute = len(travel_by_minute) - 1

    moves = [(n, dr, dc, jumped_cells(dr, dc)) for n, (dr, dc) in enumerate(NEIGHBOURS_16)]
    can_burn = burnable.ravel().tolist()
    arrival = [math.inf] * (rows * cols)
    heap = []
    for i in np.flatnonzero(seed_mask).tolist():
        arrival[i] = 0.0
        heap.append((0.0, i))
    heapq.heapify(heap)

    while heap:
        t, i = heapq.heappop(heap)
        if t > arrival[i]:
            continue
        if t > horizon_min:
            break
        r, c = divmod(i, cols)
        step_min = travel_by_minute[min(int(t), last_minute)]
        for n, dr, dc, jumped in moves:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols):
                continue
            j = rr * cols + cc
            if not can_burn[j]:
                continue
            if jumped and not all(can_burn[(r + jr) * cols + c + jc] for jr, jc in jumped):
                continue
            t_j = t + step_min[n]
            if t_j < arrival[j]:
                arrival[j] = t_j
                heapq.heappush(heap, (t_j, j))

    out = np.array(arrival).reshape(rows, cols)
    out[out > horizon_min] = np.nan
    return out.astype(np.float32)
