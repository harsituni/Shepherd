"""Step 0 wildfire spread: a grid-based fake fire that grows from the picked point.

Follows the WildfireSim interface and Step 0 rules in shared/contract.md and
AGENT_CONTEXT.md: centred on (lat, lon), starts at a 300 m radius, spreads at
40 m per simulated minute in calm wind, never reaches past 5 km.

How it spreads:
    The area is a square grid of CELL_M cells. Every cell gets an arrival time:
    the earliest minute fire can reach it from a burning neighbour, with travel
    time = distance / rate of spread in that direction (Dijkstra over 16
    neighbours, which keeps grid distortion small). step() burns every cell whose
    arrival time has passed.

    Directional rate comes from an ellipse with the ignition at its rear focus,
    the standard elliptical fire-growth shape: fast at the head (downwind), slow at
    the back, in between on the flanks. Calm wind gives a circle; wind stretches
    it into a downwind oval.

Swapping in a real engine:
    Only PlaceholderSpread knows any fire behaviour. A replacement needs
    rates(col, row) -> (head_ros_m_per_min, length_to_breadth, head_bearing_deg)
    for the cell, e.g. ROS / LB / RAZ from CFFDRS FBP. Because rates are per cell,
    fuel or terrain that varies across the grid works without touching the spread.

Usage:
    python -m backend.sim.wildfire                   # ASCII animation, default wind
    python engine/spread0.py 0                    # calm: circle
    python engine/spread0.py 35 270 0.9           # wind_kmh wind_from_deg fuel_dryness
"""

import heapq
import math

START_RADIUS_M = 300
BASE_ROS_M_PER_MIN = 40
MAX_RADIUS_M = 5000
CELL_M = 100
OUTLINE_POINTS = 32
M_PER_DEG_LAT = 111320

NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1),
              (1, 1), (1, -1), (-1, 1), (-1, -1),
              (1, 2), (1, -2), (-1, 2), (-1, -2),
              (2, 1), (2, -1), (-2, 1), (-2, -1)]


class PlaceholderSpread:
    """Made-up fire behaviour, uniform across the grid. Not a fire model."""

    def __init__(self, wind_kmh, wind_from_deg, fuel_dryness):
        wind_kmh = max(wind_kmh, 0)
        # 40 m/min in calm wind at default dryness, faster with wind and dry fuel
        self.head_ros = BASE_ROS_M_PER_MIN * (0.3 + fuel_dryness) * (1 + wind_kmh / 20)
        # FBP length-to-breadth from wind speed: 1 when calm, ~2.6 at 20 km/h
        self.lb = 1 + 8.729 * (1 - math.exp(-0.030 * wind_kmh)) ** 2.155
        # Fire runs the way the wind blows toward
        self.head_bearing = (wind_from_deg + 180) % 360

    def rates(self, _col, _row):
        return self.head_ros, self.lb, self.head_bearing


def directional_ros(head_ros, lb, head_bearing, bearing):
    # Ellipse with the ignition at its rear focus: r(t) = a(1 - e^2) / (1 - e cos t)
    e = math.sqrt(1 - 1 / lb ** 2)
    a = head_ros / (1 + e)
    theta = math.radians(bearing - head_bearing)
    return a * (1 - e * e) / (1 - e * math.cos(theta))


class WildfireSim:
    def __init__(self, lat: float, lon: float, wind_kmh: float = 20,
                 wind_from_deg: float = 315, fuel_dryness: float = 0.7):
        self.lat = lat
        self.lon = lon
        self.model = PlaceholderSpread(wind_kmh, wind_from_deg, fuel_dryness)
        self.minutes = 0
        self.burning = set()
        self.arrival = {}
        self._frontier = []
        n = START_RADIUS_M // CELL_M
        for col in range(-n, n + 1):
            for row in range(-n, n + 1):
                if math.hypot(col, row) * CELL_M <= START_RADIUS_M:
                    self.arrival[(col, row)] = 0
                    heapq.heappush(self._frontier, (0, (col, row)))
        self._burn_until(0)

    def step(self, minutes: int) -> None:
        self.minutes += minutes
        self._burn_until(self.minutes)

    def features(self) -> list[dict]:
        cx = sum(c for c, _ in self.burning) / len(self.burning)
        cy = sum(r for _, r in self.burning) / len(self.burning)
        ring = [self._to_lonlat(*self._edge(cx, cy, 2 * math.pi * i / OUTLINE_POINTS))
                for i in range(OUTLINE_POINTS)]
        ring.append(ring[0])
        return [{
            "type": "Feature",
            "id": "hz_sim_fire",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }]

    def _burn_until(self, t):
        # Dijkstra, paused at time t: pop cells that have caught fire, and offer each
        # unburnt neighbour an earlier arrival time if fire gets there sooner this way
        while self._frontier and self._frontier[0][0] <= t:
            at, cell = heapq.heappop(self._frontier)
            if cell in self.burning or at > self.arrival[cell]:
                continue
            self.burning.add(cell)
            head_ros, lb, head_bearing = self.model.rates(*cell)
            for dc, dr in NEIGHBOURS:
                nxt = (cell[0] + dc, cell[1] + dr)
                if nxt in self.burning or math.hypot(*nxt) * CELL_M > MAX_RADIUS_M:
                    continue
                bearing = math.degrees(math.atan2(dc, dr))
                ros = directional_ros(head_ros, lb, head_bearing, bearing)
                if ros <= 0:
                    continue
                reach = at + math.hypot(dc, dr) * CELL_M / ros
                if reach < self.arrival.get(nxt, math.inf):
                    self.arrival[nxt] = reach
                    heapq.heappush(self._frontier, (reach, nxt))

    def _edge(self, cx, cy, angle):
        # Walk out from the burnt area's centre in half-cell steps until leaving the
        # burning cells, then return the last burning cell's outer edge as (east_m, north_m)
        dx, dy = math.sin(angle), math.cos(angle)
        dist = 0.0
        while True:
            nxt = dist + 0.5
            if (round(cx + nxt * dx), round(cy + nxt * dy)) not in self.burning:
                break
            dist = nxt
        dist += 0.5
        return (cx + dist * dx) * CELL_M, (cy + dist * dy) * CELL_M

    def _to_lonlat(self, east_m, north_m):
        dlat = north_m / M_PER_DEG_LAT
        dlon = east_m / (M_PER_DEG_LAT * math.cos(math.radians(self.lat)))
        return [round(self.lon + dlon, 6), round(self.lat + dlat, 6)]


def _render(sim, half_cells):
    rows = []
    for row in range(half_cells, -half_cells - 1, -1):
        rows.append("".join(
            "@" if (col, row) == (0, 0) else "#" if (col, row) in sim.burning else "."
            for col in range(-half_cells, half_cells + 1)))
    return "\n".join(rows)


if __name__ == "__main__":
    import sys
    import time

    args = [float(a) for a in sys.argv[1:4]]
    sim = WildfireSim(53.535, -113.663, *args)
    half = 20
    for minute in range(0, 31):
        if minute:
            sim.step(1)
        print("\033[2J\033[H", end="")
        m = sim.model
        print(f"sim_time {minute} min   head {m.head_ros:.0f} m/min   L:B {m.lb:.2f}   "
              f"heading {m.head_bearing:.0f} deg   burning cells {len(sim.burning)}")
        print(_render(sim, half))
        time.sleep(0.15)
    ring = sim.features()[0]["geometry"]["coordinates"][0]
    print(f"\nPolygon: {len(ring)} coords, closed={ring[0] == ring[-1]}, first={ring[0]}")
