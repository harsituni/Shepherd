"""Step 0 straight-line prototype; no road or hazard analysis is performed.

Inputs are lists of GeoJSON Features, as defined in shared/contract.md.
Eligibility means open with occupancy below capacity. Distance is great-circle
distance; ETA uses an illustrative 5 km/h and is not a travel-time prediction.
These lines are not verified as safe, drivable, or hazard-free.
"""

from math import asin, ceil, cos, radians, sin, sqrt


class NoRouteError(Exception):
    """Raised when no open shelter with spare capacity is available."""


def load_graph() -> None:
    """Startup placeholder: Step 0 loads no graph and needs no routing libraries."""
    return None


def _distance_km(lat: float, lon: float, shelter_lat: float,
                 shelter_lon: float) -> float:
    """Haversine distance on a sphere with mean Earth radius 6371.0088 km."""
    delta_lat = radians(shelter_lat - lat)
    delta_lon = radians(shelter_lon - lon)
    a = (sin(delta_lat / 2) ** 2
         + cos(radians(lat)) * cos(radians(shelter_lat))
         * sin(delta_lon / 2) ** 2)
    return 6371.0088 * 2 * asin(sqrt(max(0.0, min(1.0, a))))


def find_route(lat: float, lon: float,
               hazards: list[dict],
               shelters: list[dict]) -> dict:
    """Return the contract's GET /route body for the nearest eligible shelter.

    Hazards are accepted but deliberately ignored in Step 0. Ties select the
    first shelter in input order. No road reachability is evaluated. The API
    layer is responsible for translating NoRouteError into the contract's 404.
    """
    nearest = None
    distance = float("inf")
    for shelter in shelters:
        properties = shelter["properties"]
        if not properties["open"] or properties["occupancy"] >= properties["capacity"]:
            continue
        shelter_lon, shelter_lat = shelter["geometry"]["coordinates"]
        candidate_distance = _distance_km(lat, lon, shelter_lat, shelter_lon)
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
    """Step 2 placeholder returning []; this does not establish roads are open."""
    return []
