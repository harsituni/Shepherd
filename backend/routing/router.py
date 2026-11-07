"""Routing: straight-line multi-option routes (v2). Road-graph path lands later."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Callable, Optional

ArrivalMinFn = Callable[[float, float], Optional[int]]

BUFFER_MIN = 30  # close road 30 min before fire arrives
SPEED_KMH = 40


class NoRouteError(Exception):
    """Raised when no shelter is reachable / no usable route."""


def load_graph() -> None:
    """Step 0 / fallback: no road graph yet."""
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * asin(sqrt(max(0.0, min(1.0, a))))


def _status_for_margin(margin_min: int) -> str:
    if margin_min >= 60:
        return "ok"
    if margin_min >= 0:
        return "tight"
    return "blocked"


def _option_for_shelter(
    lat: float,
    lon: float,
    shelter: dict,
    route_id: str,
    arrival_min_fn: ArrivalMinFn,
    sim_time: int,
) -> dict:
    shelter_lon, shelter_lat = shelter["geometry"]["coordinates"]
    distance_km = round(_haversine_km(lat, lon, shelter_lat, shelter_lon), 1)
    eta_min = max(1, round(distance_km / SPEED_KMH * 60))

    # Sample along the straight line (start → mid → shelter).
    samples = [
        (0.0, lat, lon),
        (0.5, (lat + shelter_lat) / 2, (lon + shelter_lon) / 2),
        (1.0, shelter_lat, shelter_lon),
    ]

    leave_by_candidates: list[int] = []
    clear_until: Optional[int] = None
    block_reason: Optional[str] = None

    for frac, plat, plon in samples:
        fire_at = arrival_min_fn(plat, plon)
        if fire_at is None:
            continue
        deadline = fire_at - BUFFER_MIN  # must be there by this sim minute
        drive_offset = round(frac * eta_min)
        # Latest start time so driver still beats the buffer at this sample.
        leave_by_candidates.append(deadline - drive_offset)
        if clear_until is None or deadline < clear_until:
            clear_until = deadline
        # If leaving now would miss this sample, record a reason.
        arrive_if_now = sim_time + drive_offset
        if arrive_if_now > deadline and block_reason is None:
            block_reason = (
                f"Fire arrives near "
                f"({plat:.3f}, {plon:.3f}) at T+{fire_at}; "
                f"you would reach it at T+{arrive_if_now} "
                f"(needs T+{deadline} with {BUFFER_MIN} min buffer)."
            )

    if leave_by_candidates:
        leave_by = min(leave_by_candidates)
        margin_min = leave_by - sim_time
    else:
        # No fire on path within horizon — treat as wide-open.
        leave_by = None
        margin_min = 999
        clear_until = None

    status = _status_for_margin(margin_min)
    if status != "blocked":
        block_reason = None
    elif block_reason is None:
        block_reason = "Route intersects the predicted fire with less than a 30 min buffer."

    return {
        "id": route_id,
        "shelter_id": shelter["id"],
        "shelter_name": shelter["properties"]["name"],
        "distance_km": distance_km,
        "eta_min": eta_min,
        "margin_min": margin_min if margin_min != 999 else 999,
        "status": status,
        "clear_until_sim_min": clear_until if status != "blocked" else None,
        "clear_until_label": (
            f"Clear until T+{clear_until}" if status != "blocked" and clear_until is not None else None
        ),
        "reason": block_reason,
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat], [shelter_lon, shelter_lat]],
        },
        # Internal: used to pick top-level leave_by for this option
        "_leave_by": leave_by,
    }


def find_routes(
    lat: float,
    lon: float,
    arrival_min_fn: ArrivalMinFn,
    shelters: list[dict],
    sim_time: int = 0,
) -> dict:
    """Return the GET /route v2 body (options, leave_by_*, etc.)."""
    open_shelters = [s for s in shelters if s.get("properties", {}).get("open")]
    if not open_shelters:
        raise NoRouteError("No reachable shelter from this location")

    # Prefer nearer shelters first; keep up to 3 options.
    ranked = sorted(
        open_shelters,
        key=lambda s: _haversine_km(
            lat, lon, s["geometry"]["coordinates"][1], s["geometry"]["coordinates"][0]
        ),
    )[:3]

    options = []
    for i, shelter in enumerate(ranked, start=1):
        opt = _option_for_shelter(
            lat, lon, shelter, f"rt_{i}", arrival_min_fn, sim_time
        )
        options.append(opt)

    usable = [o for o in options if o["status"] in ("ok", "tight")]
    if not usable:
        raise NoRouteError("No usable evacuation route under the current fire forecast")

    # Best = highest margin among usable, then shorter ETA.
    best = max(usable, key=lambda o: (o["margin_min"], -o["eta_min"]))
    leave_by = best.get("_leave_by")
    if leave_by is None:
        leave_by_label = None
    else:
        wait = leave_by - sim_time
        leave_by_label = f"Leave within {max(0, wait)} min (sim)"

    excluded = [
        {"shelter_id": o["shelter_id"], "reason": o["reason"] or "Blocked"}
        for o in options
        if o["status"] == "blocked"
    ]

    # Strip internal fields and build response.
    clean_options = []
    for o in options:
        o = dict(o)
        o.pop("_leave_by", None)
        if o["margin_min"] == 999:
            # Cap display margin when no fire threat.
            o["margin_min"] = 999
        clean_options.append(o)

    body = {
        "lat": lat,
        "lon": lon,
        "sim_time": sim_time,
        "leave_by_sim_min": leave_by,
        "leave_by_label": leave_by_label,
        "best_route_id": best["id"],
        "options": clean_options,
        "excluded": excluded,
    }

    # Step 0 compatibility: flat fields from the best usable option.
    body.update(
        {
            "shelter_id": best["shelter_id"],
            "shelter_name": best["shelter_name"],
            "distance_km": best["distance_km"],
            "eta_min": best["eta_min"],
            "geometry": best["geometry"],
            "rerouted": False,
            "reroute_reason": None,
            "steps": [],
        }
    )
    return body


def check_route(
    lat: float,
    lon: float,
    route_id: str,
    arrival_min_fn: ArrivalMinFn,
    shelters: list[dict],
    sim_time: int = 0,
) -> dict:
    """Re-validate a chosen route; same response shape as find_routes."""
    body = find_routes(lat, lon, arrival_min_fn, shelters, sim_time=sim_time)
    # Prefer the checked id when it is still present and usable.
    for opt in body["options"]:
        if opt["id"] == route_id and opt["status"] in ("ok", "tight"):
            body["best_route_id"] = route_id
            body["shelter_id"] = opt["shelter_id"]
            body["shelter_name"] = opt["shelter_name"]
            body["distance_km"] = opt["distance_km"]
            body["eta_min"] = opt["eta_min"]
            body["geometry"] = opt["geometry"]
            break
    return body


def find_route(
    lat: float,
    lon: float,
    hazards: list[dict],
    shelters: list[dict],
) -> dict:
    """Step 0 single-route helper (nearest open shelter). Hazards ignored."""
    _ = hazards
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
    eta_min = round(distance_km / SPEED_KMH * 60)

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
