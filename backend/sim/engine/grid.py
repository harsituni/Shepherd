"""bbox → UTM 12N grid, perimeter rasterisation and the shared affine transform.

Row 0 is the northernmost row. origin_xy is the outer top-left corner of cell
(0, 0), so cell (r, c) centre = (origin_x + (c + 0.5) * cell_m,
origin_y - (r + 0.5) * cell_m).
"""

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import box
from pyproj import Transformer
from rasterio import features
from rasterio.transform import Affine

GRID_CRS = "EPSG:32612"
TO_UTM = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
TO_WGS84 = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
DEFAULT_CELL_M = 100
DOMAIN_SEGMENT_DEG = 0.001  # <=112 m along latitude/longitude in the supported zone


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
    # Use exactly the same projected boundary as the burnable-domain mask.
    left, bottom, right, top = projected_domain(bbox).bounds
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


def _xy_transform(transformer):
    """Adapt pyproj Transformer to shapely 2.0's (N, 2) coordinate callback.

    shapely>=2.1 accepts ``interleaved=False`` and a (x, y) → (x, y) callable;
    2.0 (Python 3.9 wheels) only takes an (N, 2) ndarray callback.
    """

    def apply(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        out = np.empty_like(coords)
        out[:, 0] = x
        out[:, 1] = y
        return out

    return apply


def to_utm(geom):
    return shapely.transform(geom, _xy_transform(TO_UTM))


def to_wgs84(geom):
    return shapely.transform(geom, _xy_transform(TO_WGS84))


def projected_domain(bbox):
    """Project the geographic box's curved sides, not just its four corners.

    Straight chords between projected corners can exclude roads inside the
    geographic bbox (F08, 66 Street SW). Densification is shared by grid bounds,
    engine rasterization and the oracle; it does not alter propagation rates.
    """
    return to_utm(shapely.segmentize(box(*bbox), DOMAIN_SEGMENT_DEG))


def domain_mask(bbox, grid):
    """Modeled cells whose closed squares intersect the projected domain.

    GDAL all_touched can miss thin intersections or include nearby disjoint
    cells depending on segment subdivision. Use geometric intersections for
    the domain boundary; keep ignition rasterization unchanged. Chunking bounds
    temporary geometry memory even for the engine's largest supported grid.
    """
    domain = projected_domain(bbox)
    shapely.prepare(domain)
    mask = np.empty(grid.rows * grid.cols, dtype=bool)
    for start in range(0, len(mask), 8192):
        flat = np.arange(start, min(start + 8192, len(mask)))
        row, col = np.divmod(flat, grid.cols)
        left = grid.origin_x + col * grid.cell_m
        top = grid.origin_y - row * grid.cell_m
        cells = shapely.box(left, top - grid.cell_m, left + grid.cell_m, top)
        mask[flat] = shapely.intersects(domain, cells)
    return mask.reshape(grid.shape)


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
