"""Cumulative perimeter frames (B2): polygonise arrival <= T, reproject to WGS84.

Frames are clipped to the scenario bbox, because the grid is snapped outward
and can extend slightly past it.
"""

import numpy as np
from rasterio import features
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union

from backend.sim.engine.grid import to_wgs84

COORD_DECIMALS = 6


def _polygons(geom):
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    return [p for part in getattr(geom, "geoms", []) for p in _polygons(part)]


def _rounded(coords):
    if isinstance(coords[0], (int, float)):
        return [round(v, COORD_DECIMALS) for v in coords]
    return [_rounded(c) for c in coords]


def burned_geometry(mask, grid, bbox) -> dict:
    """GeoJSON MultiPolygon (WGS84) of the True cells; empty coordinates if none."""
    if not mask.any():
        return {"type": "MultiPolygon", "coordinates": []}
    cells = [
        shape(geom)
        for geom, _ in features.shapes(
            mask.astype(np.uint8), mask=mask, transform=grid.transform
        )
    ]
    burned = unary_union(cells).simplify(grid.cell_m / 2, preserve_topology=True)
    clipped = to_wgs84(burned).intersection(box(*bbox))
    polygons = _polygons(clipped)
    if not polygons:
        return {"type": "MultiPolygon", "coordinates": []}
    return {
        "type": "MultiPolygon",
        "coordinates": _rounded(mapping(MultiPolygon(polygons))["coordinates"]),
    }


def perimeter_frames(arrival, grid, bbox, horizon_min, step_min, band) -> list[dict]:
    """One Feature per t_min = 0, step_min, ..., horizon_min."""
    frames = []
    for t in range(0, horizon_min + 1, step_min):
        with np.errstate(invalid="ignore"):
            mask = arrival <= t
        frames.append({
            "type": "Feature",
            "properties": {"t_min": t, "band": band},
            "geometry": burned_geometry(mask, grid, bbox),
        })
    return frames
