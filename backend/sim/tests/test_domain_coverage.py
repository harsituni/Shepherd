"""Domain projection regressions, independent of routing classifications."""

import numpy as np
import shapely
from shapely.geometry import Point, box

from backend.sim.engine.grid import build_grid, domain_mask, seed_mask, to_utm
from backend.sim.wildfire import WildfireSim


BBOX = [-113.7823698, 53.3957966, -113.2461184, 53.6324171]


def test_geographic_south_edge_is_not_replaced_by_projected_corner_chord():
    grid = build_grid(BBOX)
    point = to_utm(Point(-113.442712, 53.395873))
    row, col = grid.cell_of(point.x, point.y)
    # Establish the original defect and compare with a 10x finer independent boundary.
    old = seed_mask(to_utm(box(*BBOX)), grid)
    fine_domain = to_utm(shapely.segmentize(box(*BBOX), .0001))
    xs, ys = np.meshgrid(grid.origin_x + (np.arange(grid.cols) + 0.5) * grid.cell_m,
                         grid.origin_y - (np.arange(grid.rows) + 0.5) * grid.cell_m)
    cells = shapely.box(xs - 50, ys - 50, xs + 50, ys + 50)
    reference = shapely.intersects(cells, fine_domain)
    assert not old[row, col]
    assert reference[row, col]
    got = domain_mask(BBOX, grid)
    np.testing.assert_array_equal(got, reference)
    # GDAL's all_touched itself misses/includes slivers depending on subdivision.
    assert got[60, 7] and not got[3, 95] and not got[72, 363]


def test_engine_and_oracle_model_the_same_domain_without_retiming_interior():
    narrow = WildfireSim(53.535, -113.663, wind_kmh=35, wind_from_deg=270)
    wide = WildfireSim(53.535, -113.663, wind_kmh=35, wind_from_deg=270, domain_bbox=BBOX)
    oracle = wide.oracle()
    np.testing.assert_array_equal(oracle.in_domain,
                                  domain_mask(wide._bbox, wide._result.grid).ravel())
    # Whole-cell arrivals in the common interior stay identical after enlarging the domain.
    a = narrow.oracle()
    rows, cols = np.indices((a.nrows, a.ncols))
    x = a.x0 + (cols.ravel() + .5) * a.cell_m
    y = a.y0 - (rows.ravel() + .5) * a.cell_m
    rr = np.floor((oracle.y0 - y) / oracle.cell_m).astype(int)
    cc = np.floor((x - oracle.x0) / oracle.cell_m).astype(int)
    finite = np.isfinite(a.arrival)
    assert finite.sum() > 1000
    np.testing.assert_array_equal(a.arrival[finite], oracle.arrival[rr * oracle.ncols + cc][finite])
