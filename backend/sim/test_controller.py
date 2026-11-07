import unittest

from backend.sim.controller import SimController


class SimControllerTests(unittest.TestCase):
    def test_fresh_status_is_idle(self):
        c = SimController()
        s = c.status()
        self.assertEqual(s["state"], "idle")
        self.assertIsNone(s["scenario"])
        self.assertEqual(s["sim_time"], 0)
        self.assertEqual(s["speed"], 1)

    def test_start_running(self):
        c = SimController()
        s = c.start(
            {
                "scenario": "wildfire",
                "lat": 53.535,
                "lon": -113.663,
                "wind_kmh": 20,
                "wind_from_deg": 315,
                "fuel_dryness": 0.7,
            }
        )
        self.assertEqual(s["state"], "running")
        self.assertEqual(s["scenario"], "wildfire")
        self.assertEqual(s["sim_time"], 0)
        self.assertTrue(c.features())

    def test_tick_advances_when_running(self):
        c = SimController()
        c.start(
            {
                "scenario": "wildfire",
                "lat": 53.535,
                "lon": -113.663,
            }
        )
        c.set_speed(4)
        c.tick()
        self.assertEqual(c.sim_time, 4)

    def test_pause_stops_advancement(self):
        c = SimController()
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.pause()
        c.tick()
        self.assertEqual(c.sim_time, 0)
        self.assertEqual(c.state, "paused")

    def test_resume_continues(self):
        c = SimController()
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.pause()
        c.resume()
        c.tick()
        self.assertEqual(c.state, "running")
        self.assertEqual(c.sim_time, 1)

    def test_reset_clears(self):
        c = SimController()
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.tick()
        s = c.reset()
        self.assertEqual(s["state"], "idle")
        self.assertIsNone(s["scenario"])
        self.assertEqual(s["sim_time"], 0)
        self.assertEqual(c.features(), [])

    def test_flood_rejected(self):
        c = SimController()
        with self.assertRaises(ValueError):
            c.start({"scenario": "flood", "lat": 53.5, "lon": -113.5})


if __name__ == "__main__":
    unittest.main()
