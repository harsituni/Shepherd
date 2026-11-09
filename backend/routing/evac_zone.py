"""Evacuation-zone geometry shared with dashboard/phone `evacuation.js`.

A shelter is unsafe when it lies inside a 1 km circle around the current fire
or any forecast outline. Routing uses the same rule so the phone never
recommends a centre the dashboard already paints red.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

EVAC_BUFFER_M = 1000
M_PER_DEG_LAT = 111320.0
CIRCLE_STEPS = 64


def _centroid(ring: list) -> tuple[float, float]:
    pts = ring[:-1] if len(ring) > 1 else ring
    if not pts:
        return 0.0, 0.0
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


def evac_circle(ring: list, margin_m: float = EVAC_BUFFER_M) -> list:
    """Closed ring: circle centred on `ring`, radius = farthest vertex + margin."""
    cx, cy = _centroid(ring)
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(cy * math.pi / 180.0)
    reach = 0.0
    for x, y in ring:
        reach = max(reach, math.hypot((x - cx) * m_per_deg_lon, (y - cy) * M_PER_DEG_LAT))
    radius = reach + margin_m
    circle = []
    for i in range(CIRCLE_STEPS):
        angle = (i / CIRCLE_STEPS) * 2 * math.pi
        circle.append([
            cx + (radius * math.sin(angle)) / m_per_deg_lon,
            cy + (radius * math.cos(angle)) / M_PER_DEG_LAT,
        ])
    circle.append(circle[0])
    return circle


def _point_in_ring(point: tuple[float, float], ring: list) -> bool:
    x, y = point
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 0.0) + xi):
            inside = not inside
        j = i
    return inside


def _is_fire_now(feature: dict) -> bool:
    """Current core hazard that paints an evacuation circle (wildfire or tornado)."""
    props = feature.get("properties") or {}
    return (
        props.get("kind") in ("wildfire", "tornado")
        and props.get("zone") == "core"
        and props.get("predicted_min") is None
        and (feature.get("geometry") or {}).get("type") == "Polygon"
    )


def danger_rings(hazards: Optional[dict], forecast_outlines: Optional[Iterable] = None) -> list:
    """Evacuation circles for the fire now and each forecast outline."""
    rings = []
    for feature in (hazards or {}).get("features") or []:
        if not _is_fire_now(feature):
            continue
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if coords:
            rings.append(evac_circle(coords[0]))
    for outline in forecast_outlines or []:
        geom = outline.get("geometry") or {}
        if geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates") or []
        if coords:
            rings.append(evac_circle(coords[0]))
    return rings


def unsafe_shelter_ids(shelters: list, rings: list) -> set:
    unsafe = set()
    for shelter in shelters or []:
        coords = (shelter.get("geometry") or {}).get("coordinates")
        if not coords or len(coords) < 2:
            continue
        point = (float(coords[0]), float(coords[1]))
        if any(_point_in_ring(point, ring) for ring in rings):
            unsafe.add(shelter["id"])
    return unsafe


def mark_unsafe_shelters(options: list, unsafe_ids: set) -> list:
    """Force options whose destination is in the evacuation zone to `blocked`."""
    if not unsafe_ids:
        return options
    out = []
    for option in options:
        if option.get("shelter_id") in unsafe_ids and option.get("status") in ("ok", "tight"):
            name = option.get("shelter_name") or "this shelter"
            option = {
                **option,
                "status": "blocked",
                "margin_min": option.get("margin_min") if option.get("margin_min") is not None and option["margin_min"] < 0 else -1,
                "leave_by_sim_min": None,
                "clear_until_sim_min": None,
                "clear_until_label": None,
                "reason": f"Fire is already near {name} (inside the evacuation zone).",
            }
        out.append(option)
    return out
