"""Leave-by must not jump when the engine extends its forecast horizon."""

import unittest
from dataclasses import replace

import numpy as np

from backend.routing.road_graph import TO_GRID
from backend.routing.safety import (
    COVERAGE_HORIZON_MIN,
    COVERAGE_SLACK_MIN,
    RoutePath,
    judge,
)
from backend.routing.v3_testing import Forecast, grid_around, ll


class LeaveByHorizonTests(unittest.TestCase):
    def test_leave_by_stable_when_covers_until_extends(self):
        # No fire on the route: leave-by is coverage-capped. Extending the engine
        # horizon (LOOKAHEAD) used to push leave-by upward mid-evacuation.
        pin = ll(0, 0)
        dest = ll(2000, 0)
        pin_xy = TO_GRID.transform(*pin)
        dest_xy = TO_GRID.transform(*dest)
        fc = Forecast(grid_around([pin, dest]))
        path = RoutePath(
            pin, pin_xy, pin, pin_xy,
            np.array([], dtype=np.int64), 2000.0,
            dest, dest_xy, "T", access_verified=True,
        )
        t_now = 200
        short = fc.oracle(sim_time=t_now, covers_until=t_now + COVERAGE_HORIZON_MIN)
        long = replace(short, covers_until_sim_min=float(t_now + COVERAGE_HORIZON_MIN + 250))
        a = judge(path, t_now, short, None)
        b = judge(path, t_now, long, None)
        self.assertEqual(a.status, "ok")
        self.assertIsNotNone(a.leave_by_sim_min)
        self.assertEqual(a.leave_by_sim_min, b.leave_by_sim_min)
        expected = int(t_now + COVERAGE_HORIZON_MIN - COVERAGE_SLACK_MIN - path.total_min)
        self.assertEqual(a.leave_by_sim_min, expected)


if __name__ == "__main__":
    unittest.main()
