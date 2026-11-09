"""FIFO earliest arrivals on a 16-neighbour grid.

Directional rates are sampled in physical time, interpolated linearly, and
integrated through the ENTIRE crossing. See backend/sim/README.md ("The engine").
"""

import bisect
import heapq
import math

import numpy as np

from backend.sim.engine import fbp

# (d_row, d_col); north = -d_row, east = +d_col.
NEIGHBOURS_16 = (
    (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1),
    (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1),
)



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


class DirectionalTravel:
    """Integral and inverse integral of nonnegative piecewise-linear rates.

    No rate threshold: arbitrarily small positive rates accumulate distance.
    Flat cumulative sections represent waiting through zero spread conditions.
    """

    def __init__(self, times, rates):
        times = np.asarray(times, dtype=float)
        rates = np.asarray(rates, dtype=float)
        if (times.ndim != 1 or len(times) < 2 or times[0] != 0
                or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0)
                or rates.ndim != 2 or rates.shape[0] != len(times)
                or not np.all(np.isfinite(rates)) or np.any(rates < 0)):
            raise ValueError("times must increase from zero; rates must be finite and nonnegative")
        dt = np.diff(times)
        areas = (rates[:-1] + rates[1:]) * (dt[:, None] / 2)
        cumulative = np.vstack((np.zeros(rates.shape[1]), np.cumsum(areas, axis=0)))
        self.times = times.tolist()
        self.rates = rates.T.tolist()
        self.slopes = ((rates[1:] - rates[:-1]) / dt[:, None]).T.tolist()
        self.cumulative = cumulative.T.tolist()
        self.horizon = float(times[-1])

    def arrival(self, departure, direction, distance):
        if departure < 0 or not math.isfinite(departure) or distance < 0 or not math.isfinite(distance):
            raise ValueError("departure and distance must be finite and nonnegative")
        if departure > self.horizon:
            return math.inf
        if distance == 0:
            return departure
        if departure == self.horizon:
            return math.inf
        k = bisect.bisect_right(self.times, departure) - 1
        dt = departure - self.times[k]
        rates, slopes, cumulative = self.rates[direction], self.slopes[direction], self.cumulative[direction]
        target = cumulative[k] + rates[k] * dt + 0.5 * slopes[k] * dt * dt + distance
        if target > cumulative[-1]:
            return math.inf
        end = bisect.bisect_left(cumulative, target, lo=k + 1)
        j = end - 1
        area = target - cumulative[j]
        # Stable positive quadratic root, also valid for a decreasing rate.
        root = math.sqrt(max(0.0, rates[j] ** 2 + 2 * slopes[j] * area))
        denominator = rates[j] + root
        elapsed = 2 * area / denominator if denominator > 0 else 0.0
        return min(self.times[end], max(departure, self.times[j] + elapsed))


def compute_arrival(seed_mask, burnable, weather_table, cell_m, horizon_min) -> np.ndarray:
    """First arrival minutes after t0; float32 NaN means not reached by horizon.

    Label-setting Dijkstra is valid because integrated nonnegative edge speeds
    give nondecreasing edge arrival functions (FIFO), including zero-rate waits.
    """
    seed_mask = np.asarray(seed_mask, dtype=bool)
    burnable = np.asarray(burnable, dtype=bool)
    if seed_mask.ndim != 2 or seed_mask.shape != burnable.shape or not seed_mask.any():
        raise ValueError("nonempty 2D seeds and matching burnable mask required")
    if not math.isfinite(cell_m) or cell_m <= 0 or horizon_min <= 0:
        raise ValueError("cell size and horizon must be positive")
    if np.any(seed_mask & ~burnable):
        raise ValueError("seed cells must be burnable")
    rows, cols = seed_mask.shape
    times = weather_table.times_min
    if times is None:
        times = np.arange(len(weather_table), dtype=float)
    if times[-1] < horizon_min:
        raise ValueError("weather table does not cover horizon")
    travel = DirectionalTravel(times, neighbour_rates(weather_table))
    moves = [(n, dr, dc, jumped_cells(dr, dc), math.hypot(dr, dc) * cell_m)
             for n, (dr, dc) in enumerate(NEIGHBOURS_16)]
    can_burn = burnable.ravel().tolist()
    arrival = [math.inf] * (rows * cols)
    settled = [False] * len(arrival)
    heap = []
    for i in np.flatnonzero(seed_mask).tolist():
        arrival[i] = 0.0
        heap.append((0.0, i))
    heapq.heapify(heap)
    while heap:
        t, i = heapq.heappop(heap)
        if settled[i] or t > arrival[i]:
            continue
        settled[i] = True
        r, c = divmod(i, cols)
        for n, dr, dc, jumped, distance in moves:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < rows and 0 <= cc < cols):
                continue
            j = rr * cols + cc
            if settled[j] or not can_burn[j]:
                continue
            if jumped and not all(can_burn[(r + jr) * cols + c + jc] for jr, jc in jumped):
                continue
            t_j = travel.arrival(t, n, distance)
            if t_j <= horizon_min and t_j < arrival[j]:
                arrival[j] = t_j
                heapq.heappush(heap, (t_j, j))
    out = np.array(arrival).reshape(rows, cols)
    out[~np.isfinite(out)] = np.nan
    return out.astype(np.float32)
