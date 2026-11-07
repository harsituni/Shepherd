"""Step 0 routing: straight line to the nearest open shelter (stdlib only)."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


class NoRouteError(Exception):
    """Raised when no shelter is reachable."""


def load_graph() -> None:
    """Step 0: no road graph yet."""
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * asin(sqrt(max(0.0, min(1.0, a))))


def find_route(
    lat: float,
    lon: float,
    hazards: list[dict],
    shelters: list[dict],
) -> dict:
    """Straight line to the nearest open shelter. Hazards ignored in Step 0."""
    _ = hazards  # unused until Step 1+
    nearest = None
    best_km = float("inf")

    for shelter in shelters:
        props = shelter["properties"]
        if not props.get("open"):
            continue
        shelter_lon, shelter_lat = shelter["geometry"]["coordinates"]
        km = _haversine_km(lat, lon, shelter_lat, shelter_lon)
        if km < best_km:
            nearest = shelter
            best_km = km

    if nearest is None:
        raise NoRouteError("No reachable shelter from this location")

    shelter_lon, shelter_lat = nearest["geometry"]["coordinates"]
    distance_km = round(best_km, 1)
    eta_min = round(distance_km / 40 * 60)

    return {
        "shelter_id": nearest["id"],
        "shelter_name": nearest["properties"]["name"],
        "distance_km": distance_km,
        "eta_min": eta_min,
        "rerouted": False,
        "reroute_reason": None,
        "steps": [],
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat], [shelter_lon, shelter_lat]],
        },
    }


def closed_roads(hazards: list[dict]) -> list[dict]:
    """Step 2 placeholder."""
    _ = hazards
    return []
