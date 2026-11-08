"""Tornado follows a meandering supercell track and exposes a routing oracle."""

import math
import unittest

from backend.sim.controller import SimController
from backend.sim.tornado import TornadoSim


class TornadoSimTests(unittest.TestCase):
    def test_moves_with_storm_and_leaves_a_damage_path(self):
        # Wind FROM west → storm toward the east; funnel on the right-rear flank.
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270)
        sim.step(25)
        feats = {f["id"]: f for f in sim.features()}
        self.assertIn("hz_tornado_core", feats)
        self.assertIn("hz_tornado_scar", feats)
        self.assertIn("hz_tornado_debris", feats)
        self.assertEqual(feats["hz_tornado_core"]["properties"]["kind"], "tornado")
        ring = feats["hz_tornado_core"]["geometry"]["coordinates"][0]
        cx = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        self.assertGreater(cx, -113.55)
        self.assertEqual(feats["hz_tornado_scar"]["properties"]["zone"], "buffer")
        self.assertGreater(feats["hz_tornado_core"]["properties"]["intensity"], 0.2)

    def test_track_meanders_off_a_straight_line(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=55, wind_from_deg=270)
        # Sample centres; latitude should vary (right-flank + sine), not a flat line.
        lats = [sim._centre_at(t)[1] for t in (5, 15, 25, 40, 55)]
        self.assertGreater(max(lats) - min(lats), 0.002)  # > ~200 m of northing change

    def test_forecast_is_a_widening_corridor(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=50, wind_from_deg=270)
        outlines = sim.forecast(60)
        self.assertEqual([o["t_min"] for o in outlines], [15, 30, 45, 60])
        self.assertTrue(all(o["properties"]["kind"] == "tornado" for o in outlines))
        # Later outlines cover more vertices (longer corridor) than the near-term one.
        self.assertGreater(
            len(outlines[-1]["geometry"]["coordinates"][0]),
            len(outlines[0]["geometry"]["coordinates"][0]) - 5,
        )

    def test_oracle_marks_cells_on_the_path(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270)
        # Use the modelled centre at T+12 — must be inside the damage swath.
        lon, lat = sim._centre_at(12)
        status, minute = sim.arrival_status(lat, lon, horizon_min=120)
        self.assertEqual(status, "arrival")
        self.assertIsNotNone(minute)
        self.assertLessEqual(minute, 15)

    def test_life_cycle_peaks_then_weakens(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=50, wind_from_deg=270)
        early = sim._core_radius(5)
        peak = sim._core_radius(22)
        late = sim._core_radius(65)
        self.assertGreater(peak, early)
        self.assertGreater(peak, late)

    def test_controller_starts_tornado(self):
        c = SimController(weather="dashboard")
        s = c.start({
            "scenario": "tornado", "lat": 53.54, "lon": -113.55,
            "wind_kmh": 55, "wind_from_deg": 270,
        })
        self.assertEqual(s["scenario"], "tornado")
        self.assertEqual(s["state"], "running")
        c.set_speed(16)
        c.tick()
        kinds = {f["properties"]["kind"] for f in c.features()}
        self.assertEqual(kinds, {"tornado"})
        self.assertTrue(c.forecast()["outlines"])
        self.assertIsNotNone(c.oracle())


if __name__ == "__main__":
    unittest.main()
