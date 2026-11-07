"""Analytic mock fire: one fixed ellipse growing downwind, no FBP.

Unblocks routing and backend work before the real engine is wired in. Head rate
15 m/min and LB 3, with the t = 0 wind direction held for the whole run. The
ellipse grows from the perimeter centroid, which sits at its rear focus, so
BROS follows from LB: (ROS - BROS) / (ROS + BROS) = sqrt(1 - 1/LB^2).
"""

import math

import numpy as np

from backend.sim.engine import fbp

MOCK_HEAD_ROS_M_PER_MIN = 15.0
MOCK_LB = 3.0


def mock_rates():
    """(ros, bros, fros) for the mock ellipse."""
    e = math.sqrt(1 - 1 / MOCK_LB**2)
    ros = MOCK_HEAD_ROS_M_PER_MIN
    bros = ros * (1 - e) / (1 + e)
    return ros, bros, (ros + bros) / (2 * MOCK_LB)


def mock_arrival(seed_mask, grid, centroid_xy, spread_bearing_deg, horizon_min) -> np.ndarray:
    x, y = grid.cell_centres()
    dx = x - centroid_xy[0]
    dy = y - centroid_xy[1]
    theta = np.arctan2(dx, dy) - math.radians(spread_bearing_deg)
    arrival = np.hypot(dx, dy) / fbp.directional_ros(*mock_rates(), theta)
    arrival[seed_mask] = 0.0
    arrival[arrival > horizon_min] = np.nan
    return arrival.astype(np.float32)
