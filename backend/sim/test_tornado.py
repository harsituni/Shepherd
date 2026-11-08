"""Tornado follows a meandering supercell track and exposes EF stats + oracle."""

import unittest

from backend.sim.controller import SimController
from backend.sim.tornado import TornadoSim, ef_from_steering_wind


class TornadoSimTests(unittest.TestCase):
    def test_moves_with_storm_and_leaves_a_damage_path(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270, ef_rating=3)
        sim.step(25)
        feats = {f["id"]: f for f in sim.features()}
        self.assertIn("hz_tornado_core", feats)
        self.assertIn("hz_tornado_scar", feats)
        self.assertIn("hz_tornado_debris", feats)
        core = feats["hz_tornado_core"]["properties"]
        self.assertEqual(core["kind"], "tornado")
        self.assertEqual(core["ef_peak"], 3)
        self.assertIn(core["ef_rating"], (2, 3))
        self.assertEqual(core["ef_label"], f"EF{core['ef_rating']}")
        self.assertIn(core["phase"], ("organizing", "mature", "dissipating", "remnant"))
        self.assertGreater(core["wind_est_kmh"], 100)
        self.assertGreater(core["path_width_m"], 50)
        self.assertGreater(core["track_km"], 0)
        ring = feats["hz_tornado_core"]["geometry"]["coordinates"][0]
        cx = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        self.assertGreater(cx, -113.55)

    def test_ef5_is_wider_than_ef0(self):
        weak = TornadoSim(53.54, -113.55, wind_kmh=40, wind_from_deg=270, ef_rating=0)
        strong = TornadoSim(53.54, -113.55, wind_kmh=40, wind_from_deg=270, ef_rating=5)
        weak.step(22)
        strong.step(22)
        self.assertGreater(strong.stats()["path_width_m"], weak.stats()["path_width_m"] * 1.8)
        self.assertEqual(strong.stats()["ef_peak_label"], "EF5")
        self.assertEqual(weak.stats()["ef_peak_label"], "EF0")

    def test_life_cycle_peaks_then_weakens(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=50, wind_from_deg=270, ef_rating=3)
        early = sim._core_radius(5)
        peak = sim._core_radius(22)
        late = sim._core_radius(65)
        self.assertGreater(peak, early)
        self.assertGreater(peak, late)
        self.assertEqual(sim._phase_name(4), "organizing")
        self.assertEqual(sim._phase_name(20), "mature")
        self.assertEqual(sim._phase_name(50), "dissipating")

    def test_track_meanders_off_a_straight_line(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=55, wind_from_deg=270, ef_rating=2)
        lats = [sim._centre_at(t)[1] for t in (5, 15, 25, 40, 55)]
        self.assertGreater(max(lats) - min(lats), 0.002)

    def test_forecast_carries_ef(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=50, wind_from_deg=270, ef_rating=2)
        outlines = sim.forecast(60)
        self.assertEqual([o["t_min"] for o in outlines], [15, 30, 45, 60])
        self.assertTrue(all("ef_label" in o["properties"] for o in outlines))

    def test_oracle_marks_cells_on_the_path(self):
        sim = TornadoSim(53.54, -113.55, wind_kmh=60, wind_from_deg=270, ef_rating=2)
        lon, lat = sim._centre_at(12)
        status, minute = sim.arrival_status(lat, lon, horizon_min=120)
        self.assertEqual(status, "arrival")
        self.assertIsNotNone(minute)
        self.assertLessEqual(minute, 15)

    def test_default_ef_from_wind(self):
        self.assertEqual(ef_from_steering_wind(10), 0)
        self.assertEqual(ef_from_steering_wind(40), 3)
        self.assertEqual(ef_from_steering_wind(60), 5)

    def test_controller_exposes_tornado_stats(self):
        c = SimController(weather="dashboard")
        s = c.start({
            "scenario": "tornado", "lat": 53.54, "lon": -113.55,
            "wind_kmh": 55, "wind_from_deg": 270, "ef_rating": 4,
        })
        self.assertEqual(s["scenario"], "tornado")
        self.assertEqual(s["tornado"]["ef_peak"], 4)
        self.assertEqual(s["tornado"]["ef_peak_label"], "EF4")
        c.set_speed(16)
        c.tick()
        st = c.status()
        self.assertIn(st["tornado"]["phase"], ("organizing", "mature", "dissipating", "remnant"))
        self.assertGreaterEqual(st["tornado"]["track_km"], 0)
        kinds = {f["properties"]["kind"] for f in c.features()}
        self.assertEqual(kinds, {"tornado"})


if __name__ == "__main__":
    unittest.main()
