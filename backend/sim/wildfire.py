"""Step 0 wildfire: a growing circle. Pure Python (math only)."""

from __future__ import annotations

import math


class WildfireSim:
    def __init__(
        self,
        lat: float,
        lon: float,
        wind_kmh: float = 20,
        wind_from_deg: float = 315,
        fuel_dryness: float = 0.7,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.wind_kmh = wind_kmh
        self.wind_from_deg = wind_from_deg
        self.fuel_dryness = fuel_dryness
        self.radius_m = 300.0

    def step(self, minutes: int) -> None:
        self.radius_m = min(5000.0, self.radius_m + 40.0 * minutes)

    def features(self) -> list[dict]:
        dlat = self.radius_m / 111_320
        dlon = self.radius_m / (111_320 * math.cos(math.radians(self.lat)))
        ring: list[list[float]] = []
        for i in range(32):
            angle = 2 * math.pi * i / 32
            ring.append(
                [
                    self.lon + dlon * math.cos(angle),
                    self.lat + dlat * math.sin(angle),
                ]
            )
        ring.append(ring[0])
        return [
            {
                "type": "Feature",
                "id": "hz_sim_fire",
                "properties": {
                    "kind": "wildfire",
                    "zone": "core",
                    "source": "sim",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
            }
        ]
