"""Leave-by follows the fire: it must not jump when the engine extends its forecast horizon."""

import unittest
from dataclasses import replace

import numpy as np

from backend.routing.road_graph import TO_GRID
from backend.routing.safety import BUFFER_MIN, COVERAGE_HORIZON_MIN, RoutePath, judge
from backend.routing.tests.helpers import Forecast, grid_around, ll


class LeaveByHorizonTests(unittest.TestCase):
    def test_leave_by_stable_when_covers_until_extends(self):
        # Extending the engine horizon (LOOKAHEAD) used to push leave-by upward
        # mid-evacuation. Leave-by now follows only the fire, so it can't.
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
        fire_at = t_now + 150
        fc.at_point(dest, fire_at)
        short = fc.oracle(sim_time=t_now, covers_until=t_now + COVERAGE_HORIZON_MIN)
        long = replace(short, covers_until_sim_min=float(t_now + COVERAGE_HORIZON_MIN + 250))
        a = judge(path, t_now, short, None)
        b = judge(path, t_now, long, None)
        self.assertEqual(a.status, "ok")
        self.assertEqual(a.leave_by_sim_min, b.leave_by_sim_min)
        self.assertEqual(a.leave_by_sim_min, int(fire_at - BUFFER_MIN - path.total_min))

    def test_no_fire_on_the_route_has_no_deadline(self):
        pin, dest = ll(0, 0), ll(2000, 0)
        pin_xy, dest_xy = TO_GRID.transform(*pin), TO_GRID.transform(*dest)
        fc = Forecast(grid_around([pin, dest]))
        path = RoutePath(pin, pin_xy, pin, pin_xy, np.array([], dtype=np.int64), 2000.0,
                         dest, dest_xy, "T", access_verified=True)
        j = judge(path, 200, fc.oracle(sim_time=200, covers_until=200 + COVERAGE_HORIZON_MIN), None)
        self.assertEqual(j.status, "ok")
        self.assertIsNone(j.leave_by_sim_min)

if __name__ == "__main__":
    unittest.main()
