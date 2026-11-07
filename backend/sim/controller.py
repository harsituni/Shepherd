"""In-memory simulation controller for /sim/* endpoints."""

from __future__ import annotations

from typing import Any, Optional

from backend.sim.wildfire import WildfireSim

ALLOWED_SPEEDS = (1, 4, 16)
FORECAST_HORIZON_MIN = 120


class SimController:
    def __init__(self) -> None:
        self.state: str = "idle"  # idle | running | paused
        self.scenario: Optional[str] = None
        self.sim_time: int = 0
        self.speed: int = 1
        self.wind_kmh: float = 20.0
        self.wind_from_deg: float = 315.0
        self.sim: Optional[WildfireSim] = None

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "scenario": self.scenario,
            "sim_time": self.sim_time,
            "speed": self.speed,
            "wind_kmh": self.wind_kmh,
            "wind_from_deg": self.wind_from_deg,
        }

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        scenario = body.get("scenario", "wildfire")
        if scenario == "flood":
            raise ValueError("unsupported_scenario")
        if scenario != "wildfire":
            raise ValueError("unsupported_scenario")

        lat = float(body["lat"])
        lon = float(body["lon"])
        wind_kmh = float(body.get("wind_kmh", 20))
        wind_from_deg = float(body.get("wind_from_deg", 315))
        fuel_dryness = float(body.get("fuel_dryness", 0.7))
        if "humidity_pct" in body and body["humidity_pct"] is not None:
            # High humidity → less dry fuel (simple mapping for dashboard body)
            humidity = max(0.0, min(100.0, float(body["humidity_pct"])))
            fuel_dryness = max(0.3, min(0.95, 1.0 - humidity / 100.0))

        self.sim = WildfireSim(
            lat=lat,
            lon=lon,
            wind_kmh=wind_kmh,
            wind_from_deg=wind_from_deg,
            fuel_dryness=fuel_dryness,
        )
        self.state = "running"
        self.scenario = "wildfire"
        self.sim_time = 0
        self.wind_kmh = wind_kmh
        self.wind_from_deg = wind_from_deg
        return self.status()

    def pause(self) -> dict[str, Any]:
        if self.state == "running":
            self.state = "paused"
        return self.status()

    def resume(self) -> dict[str, Any]:
        if self.state == "paused" and self.sim is not None:
            self.state = "running"
        return self.status()

    def reset(self) -> dict[str, Any]:
        self.state = "idle"
        self.scenario = None
        self.sim_time = 0
        self.speed = 1
        self.wind_kmh = 20.0
        self.wind_from_deg = 315.0
        self.sim = None
        return self.status()

    def set_speed(self, multiplier: int) -> dict[str, Any]:
        if multiplier in ALLOWED_SPEEDS:
            self.speed = multiplier
        else:
            # Nearest allowed
            self.speed = min(ALLOWED_SPEEDS, key=lambda s: abs(s - int(multiplier)))
        return self.status()

    def set_wind(self, wind_kmh: float, wind_from_deg: float) -> dict[str, Any]:
        """Apply new wind; recompute forecast/spread when a sim is active."""
        self.wind_kmh = float(wind_kmh)
        self.wind_from_deg = float(wind_from_deg) % 360
        if self.sim is not None:
            self.sim.set_wind(self.wind_kmh, self.wind_from_deg)
        return self.status()

    def tick(self) -> None:
        """Advance the sim when running. Call once per ~2s real time."""
        if self.state != "running" or self.sim is None:
            return
        minutes = self.speed
        self.sim.step(minutes)
        self.sim_time += minutes

    def features(self) -> list[dict]:
        if self.sim is None:
            return []
        return self.sim.features()

    def forecast(self) -> dict[str, Any]:
        """GET /forecast body. Empty outlines while idle (no active sim)."""
        body: dict[str, Any] = {
            "sim_time": self.sim_time,
            "horizon_min": FORECAST_HORIZON_MIN,
            "wind_kmh": self.wind_kmh,
            "wind_from_deg": self.wind_from_deg,
            "outlines": [],
        }
        if self.sim is None or self.state == "idle":
            return body
        body["outlines"] = self.sim.forecast(FORECAST_HORIZON_MIN)
        return body

    def arrival_min(self, lat: float, lon: float) -> Optional[int]:
        """Minute fire reaches this point, or None if idle / outside horizon."""
        if self.sim is None or self.state == "idle":
            return None
        return self.sim.arrival_min(lat, lon, FORECAST_HORIZON_MIN)
