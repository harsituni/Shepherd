"""Estimate how many people/cars need to evacuate near a hazard pin.

Hackathon projection (no census API): Edmonton-ish zone densities × evacuation
footprint × day/time occupancy. Good enough to set the traffic crowd from the
disaster location and clock instead of a fixed slider default.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

# America/Edmonton — Mountain time with DST.
_EDMONTON = ZoneInfo("America/Edmonton")

# Rough people / km² by local area (order: match first by distance).
# Densities are demo-scale, shaped like StatsCan / city of Edmonton ranges.
_ZONES: list[dict[str, Any]] = [
    {"name": "Downtown core", "lat": 53.5461, "lon": -113.4938, "r_km": 2.2, "day": 11000, "night": 4200},
    {"name": "University / Garneau", "lat": 53.5232, "lon": -113.5217, "r_km": 2.0, "day": 8500, "night": 5000},
    {"name": "Whyte Avenue", "lat": 53.5182, "lon": -113.4970, "r_km": 1.8, "day": 7000, "night": 4500},
    {"name": "Westmount / Inglewood", "lat": 53.5520, "lon": -113.5400, "r_km": 2.5, "day": 3200, "night": 3800},
    {"name": "Jasper Place / west end", "lat": 53.5400, "lon": -113.5800, "r_km": 3.0, "day": 2800, "night": 3400},
    {"name": "Mill Woods", "lat": 53.4600, "lon": -113.4300, "r_km": 3.5, "day": 2600, "night": 3100},
    {"name": "Clareview / northeast", "lat": 53.6000, "lon": -113.4100, "r_km": 3.0, "day": 2400, "night": 2900},
    {"name": "Castle Downs / north", "lat": 53.6300, "lon": -113.5100, "r_km": 3.0, "day": 2300, "night": 2800},
    {"name": "Terwillegar / southwest", "lat": 53.4550, "lon": -113.5800, "r_km": 3.2, "day": 2200, "night": 2700},
    {"name": "Refinery Row / east industrial", "lat": 53.5550, "lon": -113.3700, "r_km": 3.0, "day": 900, "night": 400},
]

_DEFAULT = {"name": "Edmonton suburbs", "day": 2100, "night": 2600}

# Share of people who leave by car in an urgent evac (rest walk / transit / ride).
_DRIVE_SHARE = 0.68
# Average people per evacuating vehicle.
_OCCUPANTS_PER_CAR = 1.6

_MAX_CARS = 100_000
_MIN_CARS = 500


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _parse_when(when: Optional[str]) -> datetime:
    if when:
        raw = when.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_EDMONTON)
        return dt.astimezone(_EDMONTON)
    return datetime.now(tz=_EDMONTON)


def _daypart(dt: datetime) -> tuple[str, float, bool]:
    """Return (label, occupancy_blend 0=night dens, 1=day dens, is_weekday)."""
    weekday = dt.weekday() < 5  # Mon–Fri
    h = dt.hour + dt.minute / 60.0

    if 1.0 <= h < 5.5:
        return ("late night", 0.05, weekday)
    if 5.5 <= h < 7.0:
        return ("early morning", 0.25, weekday)
    if 7.0 <= h < 9.5:
        # Rush: people on the road / still home — treat as mostly residential load.
        return ("weekday morning rush", 0.35, weekday) if weekday else ("weekend morning", 0.45, weekday)
    if 9.5 <= h < 16.0:
        return ("weekday midday", 0.95, weekday) if weekday else ("weekend midday", 0.7, weekday)
    if 16.0 <= h < 19.0:
        return ("weekday evening rush", 0.45, weekday) if weekday else ("weekend evening", 0.55, weekday)
    if 19.0 <= h < 22.5:
        return ("evening", 0.3, weekday)
    return ("night", 0.1, weekday)


def _zone_for(lat: float, lon: float) -> dict[str, Any]:
    best = None
    best_d = 1e9
    for z in _ZONES:
        d = _haversine_km(lat, lon, z["lat"], z["lon"])
        if d <= z["r_km"] and d < best_d:
            best, best_d = z, d
    if best is not None:
        return best
    # Soft falloff: nearest zone blended toward suburban default.
    for z in _ZONES:
        d = _haversine_km(lat, lon, z["lat"], z["lon"])
        if d < best_d:
            best, best_d = z, d
    return best or _DEFAULT


def _radius_km(scenario: str, wind_kmh: float = 20.0) -> float:
    """How far out we count people at ignition / touchdown."""
    s = (scenario or "wildfire").lower()
    if s == "tornado":
        # Path width + short approach buffer.
        return 1.6
    # Wildfire: yellow evac buffer ~1 km + near-term spread with wind.
    return min(4.5, 2.2 + max(0.0, wind_kmh) / 40.0)


def project_evac_demand(
    lat: float,
    lon: float,
    *,
    scenario: str = "wildfire",
    wind_kmh: float = 20.0,
    when: Optional[str] = None,
) -> dict[str, Any]:
    """Return people/cars estimate for the hazard pin at a local day/time."""
    dt = _parse_when(when)
    part, day_blend, is_weekday = _daypart(dt)
    zone = _zone_for(lat, lon)
    dens_day = float(zone.get("day", _DEFAULT["day"]))
    dens_night = float(zone.get("night", _DEFAULT["night"]))
    density = dens_night + (dens_day - dens_night) * day_blend

    # Weekends: slightly fewer downtown day workers, more people at home citywide.
    if not is_weekday:
        if "Downtown" in zone.get("name", "") or "University" in zone.get("name", ""):
            density *= 0.75 if day_blend > 0.6 else 1.05
        else:
            density *= 1.08 if day_blend < 0.5 else 0.95

    radius = _radius_km(scenario, wind_kmh)
    area = math.pi * radius * radius
    people = density * area
    # Urgency bump: denser immediate core (~40% of the disk) evacuates first.
    people *= 0.72

    cars = int(round(people * _DRIVE_SHARE / _OCCUPANTS_PER_CAR))
    cars = max(_MIN_CARS, min(_MAX_CARS, cars))
    people_i = int(round(people))

    return {
        "ok": True,
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "scenario": (scenario or "wildfire").lower(),
        "when_local": dt.isoformat(timespec="minutes"),
        "daypart": part,
        "weekday": is_weekday,
        "area_label": zone.get("name", _DEFAULT["name"]),
        "radius_km": round(radius, 2),
        "density_per_km2": int(round(density)),
        "occupancy_blend": round(day_blend, 2),
        "people": people_i,
        "cars": cars,
        "drive_share": _DRIVE_SHARE,
        "occupants_per_car": _OCCUPANTS_PER_CAR,
        "method": "edmonton_zone_density_v1",
        "label": (
            f"~{people_i:,} people / {cars:,} cars · {zone.get('name', 'area')} · {part}"
        ),
    }
