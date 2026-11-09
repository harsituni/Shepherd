"""Evacuation demand projection from pin + day/time."""

import unittest

from backend.routing.evac_demand import project_evac_demand


class EvacDemandTests(unittest.TestCase):
    def test_downtown_weekday_midday_exceeds_suburb_night(self):
        day = project_evac_demand(
            53.546, -113.494, scenario="wildfire", wind_kmh=20,
            when="2026-07-15T14:00:00-06:00",
        )
        night = project_evac_demand(
            53.455, -113.58, scenario="wildfire", wind_kmh=20,
            when="2026-07-15T02:00:00-06:00",
        )
        self.assertGreater(day["cars"], night["cars"])
        self.assertIn("Downtown", day["area_label"])
        self.assertLessEqual(day["cars"], 100_000)

    def test_tornado_smaller_footprint_than_wildfire(self):
        fire = project_evac_demand(53.54, -113.55, scenario="wildfire", wind_kmh=30, when="2026-07-15T12:00:00-06:00")
        torn = project_evac_demand(53.54, -113.55, scenario="tornado", wind_kmh=30, when="2026-07-15T12:00:00-06:00")
        self.assertGreater(fire["cars"], torn["cars"])
        self.assertLess(torn["radius_km"], fire["radius_km"])

    def test_clamped(self):
        out = project_evac_demand(53.54, -113.55, scenario="wildfire", wind_kmh=60, when="2026-07-15T12:00:00-06:00")
        self.assertGreaterEqual(out["cars"], 500)
        self.assertLessEqual(out["cars"], 100_000)


if __name__ == "__main__":
    unittest.main()
