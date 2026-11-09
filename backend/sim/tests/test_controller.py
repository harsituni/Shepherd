import unittest
from unittest.mock import patch

from backend.sim.controller import SimController
from backend.sim.weatherpipe.live import WeatherUnavailable

START = {"scenario": "wildfire", "lat": 53.535, "lon": -113.663, "wind_kmh": 25, "wind_from_deg": 90}
# 5 m/s (18 km/h) from the south for six hours.
SOUTH_WIND = [
    {"t_min": 60 * k, "wind_speed_ms": 5.0, "wind_dir_deg": 180, "temp_c": 20.0, "rh_pct": 25.0, "precip_mm": 0.0}
    for k in range(7)
]


class ForecastModeTests(unittest.TestCase):
    def test_default_mode_is_forecast(self):
        self.assertEqual(SimController().weather_mode, "forecast")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            SimController(weather="radar")

    @patch("backend.sim.controller.live_weather", return_value=(SOUTH_WIND, {"provider": "openweather"}))
    def test_forecast_wind_drives_the_fire(self, live):
        c = SimController()
        s = c.start(START)
        live.assert_called_once()
        self.assertEqual((s["wind_kmh"], s["wind_from_deg"]), (18.0, 180.0))  # not the dashboard's 25 / 90
        self.assertEqual(c.weather_source["provider"], "openweather")
        self.assertEqual(c.forecast()["wind_from_deg"], 180.0)
        c.set_speed(16)
        for _ in range(8):
            c.tick()
        ring = c.features()[0]["geometry"]["coordinates"][0]
        north = max(p[1] for p in ring) - START["lat"]
        south = START["lat"] - min(p[1] for p in ring)
        self.assertGreater(north, 2 * south)  # wind from the south pushes it north

    @patch("backend.sim.controller.live_weather", side_effect=WeatherUnavailable("offline"))
    def test_no_forecast_falls_back_to_dashboard_wind(self, _live):
        c = SimController()
        s = c.start(START)
        self.assertEqual(s["state"], "running")
        self.assertEqual((s["wind_kmh"], s["wind_from_deg"]), (25.0, 90.0))
        self.assertEqual(c.weather_source["provider"], "dashboard")
        self.assertIn("offline", c.weather_source["fallback_reason"])

    @patch("backend.sim.controller.live_weather", return_value=(SOUTH_WIND, {"provider": "openweather"}))
    def test_dashboard_wind_overrides_forecast(self, _live):
        c = SimController()
        c.start(START)
        c.tick()
        s = c.set_wind(40, 270)
        self.assertEqual((s["wind_kmh"], s["wind_from_deg"]), (40.0, 270.0))
        c.set_speed(16)
        c.tick()
        self.assertEqual(c.status()["wind_from_deg"], 270.0)  # stays overridden

    def test_dashboard_mode_never_fetches(self):
        with patch("backend.sim.controller.live_weather") as live:
            SimController(weather="dashboard").start(START)
        live.assert_not_called()


class SimControllerTests(unittest.TestCase):
    def test_fresh_status_is_idle(self):
        c = SimController(weather="dashboard")
        s = c.status()
        self.assertEqual(s["state"], "idle")
        self.assertIsNone(s["scenario"])
        self.assertEqual(s["sim_time"], 0)
        self.assertEqual(s["speed"], 1)

    def test_start_running(self):
        c = SimController(weather="dashboard")
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
        c = SimController(weather="dashboard")
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
        c = SimController(weather="dashboard")
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.pause()
        c.tick()
        self.assertEqual(c.sim_time, 0)
        self.assertEqual(c.state, "paused")

    def test_resume_continues(self):
        c = SimController(weather="dashboard")
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.pause()
        c.resume()
        c.tick()
        self.assertEqual(c.state, "running")
        self.assertEqual(c.sim_time, 1)

    def test_reset_clears(self):
        c = SimController(weather="dashboard")
        c.start({"scenario": "wildfire", "lat": 53.535, "lon": -113.663})
        c.tick()
        s = c.reset()
        self.assertEqual(s["state"], "idle")
        self.assertIsNone(s["scenario"])
        self.assertEqual(s["sim_time"], 0)
        self.assertEqual(c.features(), [])

    def test_unknown_scenario_rejected(self):
        c = SimController(weather="dashboard")
        with self.assertRaises(ValueError):
            c.start({"scenario": "other", "lat": 53.5, "lon": -113.5})

    def test_set_wind_idle_updates_state(self):
        c = SimController(weather="dashboard")
        s = c.set_wind(40, 270)
        self.assertEqual(s["wind_kmh"], 40)
        self.assertEqual(s["wind_from_deg"], 270)
        self.assertEqual(s["state"], "idle")

    def test_set_wind_running_updates_sim(self):
        c = SimController(weather="dashboard")
        c.start(
            {
                "scenario": "wildfire",
                "lat": 53.535,
                "lon": -113.663,
                "wind_kmh": 10,
                "wind_from_deg": 0,
            }
        )
        c.tick()
        before = c.features()[0]["geometry"]["coordinates"][0]
        s = c.set_wind(45, 270)
        self.assertEqual(s["wind_kmh"], 45)
        self.assertEqual(s["wind_from_deg"], 270)
        after = c.features()[0]["geometry"]["coordinates"][0]
        self.assertEqual(len(after), len(before))
        self.assertTrue(c.features())

    def test_forecast_idle_empty(self):
        c = SimController(weather="dashboard")
        body = c.forecast()
        self.assertEqual(body["outlines"], [])
        self.assertEqual(body["horizon_min"], 120)
        self.assertEqual(body["sim_time"], 0)

    def test_forecast_running_has_eight_outlines(self):
        c = SimController(weather="dashboard")
        c.start(
            {
                "scenario": "wildfire",
                "lat": 53.535,
                "lon": -113.663,
                "wind_kmh": 25,
                "wind_from_deg": 270,
            }
        )
        body = c.forecast()
        self.assertEqual(body["horizon_min"], 120)
        ts = [o["t_min"] for o in body["outlines"]]
        self.assertEqual(ts, [15, 30, 45, 60, 75, 90, 105, 120])
        for o in body["outlines"]:
            self.assertEqual(o["properties"]["zone"], "predicted")
            self.assertEqual(o["id"], f"fc_{o['t_min']}")
            ring = o["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], ring[-1])
            self.assertGreaterEqual(len(ring), 4)
        # Live footprint unchanged after forecast expand
        self.assertEqual(c.sim_time, 0)
        self.assertTrue(c.features())


if __name__ == "__main__":
    unittest.main()
