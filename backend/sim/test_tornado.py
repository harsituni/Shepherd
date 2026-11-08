"""Tornado travels with the wind and exposes a routing oracle."""

import math
import unittest

from backend.sim.controller import SimController
from backend.sim.tornado import TornadoSim


class TornadoSimTests(unittest.TestCase):
    def test_moves_downwind_and_leaves_a_scar(self):
        # Wind FROM west → travels east.
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270)
        sim.step(30)
        core = next(f for f in sim.features() if f["id"] == "hz_tornado_core")
        scar = next(f for f in sim.features() if f["id"] == "hz_tornado_scar")
        self.assertEqual(core["properties"]["kind"], "tornado")
        ring = core["geometry"]["coordinates"][0]
        cx = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        self.assertGreater(cx, -113.55)  # east of ignition
        self.assertEqual(scar["properties"]["zone"], "buffer")

    def test_forecast_outlines_ahead_of_the_funnel(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=50, wind_from_deg=270)
        outlines = sim.forecast(60)
        self.assertEqual([o["t_min"] for o in outlines], [15, 30, 45, 60])
        self.assertTrue(all(o["properties"]["kind"] == "tornado" for o in outlines))
        now = sum(p[0] for p in sim.features()[0]["geometry"]["coordinates"][0][:-1])
        later = sum(p[0] for p in outlines[-1]["geometry"]["coordinates"][0][:-1])
        self.assertGreater(later, now)

    def test_oracle_marks_cells_on_the_path(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270)
        # A point ~5 km east should be hit within an hour.
        east = -113.55 + 5000 / (111320 * math.cos(math.radians(53.54)))
        status, minute = sim.arrival_status(53.54, east, horizon_min=120)
        self.assertEqual(status, "arrival")
        self.assertIsNotNone(minute)
        self.assertLess(minute, 60)

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
