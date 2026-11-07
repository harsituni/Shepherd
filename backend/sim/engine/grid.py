"""bbox → UTM 12N grid, perimeter rasterisation and the shared affine transform.

Row 0 is the northernmost row. origin_xy is the outer top-left corner of cell
(0, 0), so cell (r, c) centre = (origin_x + (c + 0.5) * cell_m,
origin_y - (r + 0.5) * cell_m).
"""

import math
from dataclasses import dataclass

import numpy as np
import shapely
from pyproj import Transformer
from rasterio import features
from rasterio.transform import Affine

GRID_CRS = "EPSG:32612"
TO_UTM = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
TO_WGS84 = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
DEFAULT_CELL_M = 100


@dataclass(frozen=True)
class Grid:
    origin_x: float
    origin_y: float
    cell_m: int
    rows: int
    cols: int
    transform: Affine

    @property
    def shape(self):
        return self.rows, self.cols

    def cell_centres(self):
        """(x, y) arrays of shape (rows, cols) with every cell centre in metres."""
        cols = self.origin_x + (np.arange(self.cols) + 0.5) * self.cell_m
        rows = self.origin_y - (np.arange(self.rows) + 0.5) * self.cell_m
        return np.meshgrid(cols, rows)

    def cell_of(self, x, y):
        """(row, col) of the cell containing UTM point (x, y)."""
        return (
            math.floor((self.origin_y - y) / self.cell_m),
            math.floor((x - self.origin_x) / self.cell_m),
        )


def build_grid(bbox, cell_m=DEFAULT_CELL_M) -> Grid:
    """Grid covering bbox [min_lon, min_lat, max_lon, max_lat], snapped outward to cell_m."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if not isinstance(cell_m, int) or cell_m <= 0:
        raise ValueError("cell_m must be a positive integer")
    left, bottom, right, top = TO_UTM.transform_bounds(*bbox, densify_pts=21)
    min_e = math.floor(left / cell_m) * cell_m
    max_e = math.ceil(right / cell_m) * cell_m
    min_n = math.floor(bottom / cell_m) * cell_m
    max_n = math.ceil(top / cell_m) * cell_m
    return Grid(
        origin_x=float(min_e),
        origin_y=float(max_n),
        cell_m=cell_m,
        rows=round((max_n - min_n) / cell_m),
        cols=round((max_e - min_e) / cell_m),
        transform=Affine(cell_m, 0, min_e, 0, -cell_m, max_n),
    )


def to_utm(geom):
    return shapely.transform(geom, TO_UTM.transform, interleaved=False)


def to_wgs84(geom):
    return shapely.transform(geom, TO_WGS84.transform, interleaved=False)


def seed_mask(perimeter_utm, grid) -> np.ndarray:
    """Cells touched by the initial perimeter (arrival = 0).

    A perimeter too small to touch any cell seeds the cell containing its centroid.
    """
    mask = features.rasterize(
        [(perimeter_utm, 1)],
        out_shape=grid.shape,
        transform=grid.transform,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    if not mask.any():
        x, y = perimeter_utm.centroid.x, perimeter_utm.centroid.y
        row, col = grid.cell_of(x, y)
        # The declared geographic domain is closed, including outer grid edges.
        if (grid.origin_x <= x <= grid.origin_x + grid.cols * grid.cell_m
                and grid.origin_y - grid.rows * grid.cell_m <= y <= grid.origin_y):
            row, col = min(row, grid.rows - 1), min(col, grid.cols - 1)
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            raise ValueError("initial_perimeter lies outside the grid")
        mask[row, col] = True
    return mask
