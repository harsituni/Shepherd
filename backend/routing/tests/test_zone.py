"""When the evacuation zone reaches a point, and how close the fire comes to it."""

import unittest

from backend.routing.evac_zone import EVAC_BUFFER_M, fire_distance_m, zone_check
from backend.routing.tests.helpers import Forecast, circle_outlines, grid_around, ll

FIRE = ll(0, 0)


def oracle(radius_m, sim_time=0, minutes=300):
    fc = Forecast(grid_around([FIRE, ll(5000, 0)]))
    return fc.oracle(sim_time=sim_time, outlines=circle_outlines(FIRE, radius_m, minutes))


class ZoneCheckTests(unittest.TestCase):
    def test_zone_reaches_when_the_circle_covers_the_point(self):
        # Fire radius 200 + 20 m/min; the circle is 1 km more, so it covers a point
        # 3 km away once 200 + 20 m + 1000 >= 3000, at minute 90.
        z = zone_check(oracle(lambda m: 200 + 20 * m), *reversed(ll(3000, 0)), t_now=0)
        self.assertEqual(z.status, "reached")
        self.assertIn(z.reach_sim_min, (89, 90, 91))

    def test_inside_the_zone_now_is_reached_now(self):
        z = zone_check(oracle(500, sim_time=40), *reversed(ll(EVAC_BUFFER_M, 0)), t_now=40)
        self.assertEqual((z.status, z.reach_sim_min), ("reached", 40))

    def test_not_reached_within_four_hours_is_clear(self):
        z = zone_check(oracle(lambda m: 200 + 10 * m, minutes=400), *reversed(ll(5000, 0)), t_now=0)
        self.assertEqual((z.status, z.reach_sim_min), ("clear", None))  # reaches at ~380

    def test_outlines_that_end_too_soon_are_unknown(self):
        z = zone_check(oracle(200, minutes=100), *reversed(ll(5000, 0)), t_now=0)
        self.assertEqual(z.status, "unknown")

    def test_no_outlines_is_unknown(self):
        fc = Forecast(grid_around([FIRE]))
        self.assertEqual(zone_check(fc.oracle(), *reversed(FIRE), t_now=0).status, "unknown")
        self.assertEqual(zone_check(None, *reversed(FIRE), t_now=0).status, "unknown")


class FireDistanceTests(unittest.TestCase):
    def test_distance_to_the_nearest_edge_now_or_forecast(self):
        # Edge at 300 m now, 300 + 240 m by the end of the 4 h window.
        d = fire_distance_m(oracle(lambda m: 300 + m), *reversed(ll(2000, 0)), t_now=0)
        self.assertAlmostEqual(d, 2000 - 540, delta=15)

    def test_inside_the_fire_is_zero(self):
        self.assertEqual(fire_distance_m(oracle(800), *reversed(ll(100, 100)), t_now=0), 0.0)

    def test_no_outlines_is_none(self):
        self.assertIsNone(fire_distance_m(None, *reversed(FIRE), t_now=0))


if __name__ == "__main__":
    unittest.main()
