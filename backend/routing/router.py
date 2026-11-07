"""
Finds the closest available shelter to the user.

For now, the route is just a straight line.
Roads and hazards will be added later.
"""

from math import asin, ceil, cos, radians, sin, sqrt


class NoRouteError(Exception):
     """Used when no shelters are available."""


def load_graph() -> None:
    """Will load road data later."""
    return None


def _distance_km(lat: float, lon: float, shelter_lat: float,
                 shelter_lon: float) -> float:
    """Calculates the distance between two locations in km."""
    delta_lat = radians(shelter_lat - lat)
    delta_lon = radians(shelter_lon - lon)
    a = (sin(delta_lat / 2) ** 2
         + cos(radians(lat)) * cos(radians(shelter_lat))
         * sin(delta_lon / 2) ** 2)
    return 6371.0088 * 2 * asin(sqrt(max(0.0, min(1.0, a))))


def find_route(lat: float, lon: float,
               hazards: list[dict],
               shelters: list[dict]) -> dict:
    """  Finds the closest open shelter with available space.

    For now, hazards are ignored and the route is a straight line.
    """
    nearest = None
    distance = float("inf")

    for shelter in shelters:
        properties = shelter["properties"]

        if properties["open"] == False:
            continue

        if properties["occupancy"] >= properties["capacity"]:
            continue

        shelter_lon, shelter_lat = shelter["geometry"]["coordinates"]

        candidate_distance = _distance_km(
            lat, lon, shelter_lat, shelter_lon
        )

        if candidate_distance < distance:
            nearest = shelter
            distance = candidate_distance

    if nearest is None:
        raise NoRouteError("No open shelter with available capacity")

    shelter_lon, shelter_lat = nearest["geometry"]["coordinates"]
    return {
        "shelter_id": nearest["id"],
        "shelter_name": nearest["properties"]["name"],
        "distance_km": distance,
        "eta_min": ceil(distance / 5.0 * 60),
        "rerouted": False,
        "reroute_reason": None,
        "steps": [],
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat], [shelter_lon, shelter_lat]],
        },
    }


def closed_roads(hazards: list[dict]) -> list[dict]:
    """Will check for closed roads latern."""
    return []
