"""Shelters inside the dashboard evacuation buffer must not stay recommended."""

import unittest

from backend.routing.evac_zone import (
    danger_rings,
    mark_unsafe_shelters,
    shelters_closer_to_fire_than_start,
    unsafe_shelter_ids,
)
from backend.routing.safety import SHELTER_EVAC_M, RoutePath, judge
from backend.routing.tests.helpers import Forecast, grid_around, ll
from backend.routing.road_graph import TO_GRID
import numpy as np


class ShelterEvacZoneTests(unittest.TestCase):
    def test_neighbourhood_threat_does_not_block_road_judge(self):
        # Fire beside the building is a shelter_threat; road judge stays ok when
        # the journey cells are clear. Yellow-zone demotion uses hazard polygons.
        building = ll(0, 0)
        near_fire = ll(500, 0)
        dest_road = ll(50, 0)
        fc = Forecast(grid_around([building, near_fire, dest_road]))
        fc.at_point(near_fire, 0)
        b_xy = TO_GRID.transform(*building)
        r_xy = TO_GRID.transform(*dest_road)
        path = RoutePath(
            building, b_xy, building, b_xy,
            np.array([], dtype=np.int64), 50.0,
            dest_road, r_xy, "Meadows",
            access={
                "complete": True,
                "destination": {"building_point": list(building), "point": list(dest_road)},
            },
            access_verified=True,
        )
        j = judge(path, 10, fc.oracle(covers_until=200), None)
        self.assertEqual(j.status, "ok")
        self.assertEqual(j.shelter_threat_sim_min, 0)

    def test_far_fire_outside_buffer_has_no_threat(self):
        building = ll(0, 0)
        far = ll(SHELTER_EVAC_M + 400, 0)
        fc = Forecast(grid_around([building, far], margin_m=SHELTER_EVAC_M + 800))
        fc.at_point(far, 5)
        b_xy = TO_GRID.transform(*building)
        path = RoutePath(
            building, b_xy, building, b_xy,
            np.array([], dtype=np.int64), 0.0,
            building, b_xy, "Safe",
            access={"complete": True, "destination": {"building_point": list(building)}},
            access_verified=True,
        )
        j = judge(path, 0, fc.oracle(covers_until=200), None)
        self.assertEqual(j.status, "ok")
        self.assertIsNone(j.shelter_threat_sim_min)

    def test_dashboard_circle_marks_shelter_unsafe_for_routing(self):
        meadows = {
            "type": "Feature", "id": "sh_meadows",
            "properties": {"name": "The Meadows Rec Centre"},
            "geometry": {"type": "Point", "coordinates": [-113.37, 53.473]},
        }
        fire = {
            "type": "Feature", "id": "hz_1",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-113.395, 53.47], [-113.385, 53.47], [-113.385, 53.48],
                [-113.395, 53.48], [-113.395, 53.47],
            ]]},
        }
        rings = danger_rings({"type": "FeatureCollection", "features": [fire]})
        unsafe = unsafe_shelter_ids([meadows], rings)
        self.assertIn("sh_meadows", unsafe)
        option = {
            "id": "rt_sh_meadows_fastest", "shelter_id": "sh_meadows",
            "shelter_name": "The Meadows Rec Centre", "status": "ok",
            "margin_min": 80, "leave_by_sim_min": 90, "reason": None,
        }
        marked = mark_unsafe_shelters([option], unsafe)[0]
        self.assertEqual(marked["status"], "blocked")
        self.assertIsNone(marked["leave_by_sim_min"])
        self.assertIn("evacuation zone", marked["reason"])

    def test_shelter_closer_to_fire_than_start_is_rejected(self):
        # Fire west of Kinsmen; pin is farther west. Driving to Kinsmen is toward the fire.
        kinsmen = {
            "type": "Feature", "id": "sh_kinsmen",
            "properties": {"name": "Kinsmen Sports Centre"},
            "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
        }
        far = {
            "type": "Feature", "id": "sh_terwillegar",
            "properties": {"name": "Terwillegar Rec Centre"},
            "geometry": {"type": "Point", "coordinates": [-113.595, 53.440]},
        }
        fire = {
            "type": "Feature", "id": "hz_1",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-113.55, 53.515], [-113.54, 53.515], [-113.54, 53.525],
                [-113.55, 53.525], [-113.55, 53.515],
            ]]},
        }
        hazards = {"type": "FeatureCollection", "features": [fire]}
        # Start west of the fire (~-113.58). Kinsmen (~-113.52) is closer to the fire.
        closer = shelters_closer_to_fire_than_start(53.52, -113.58, [kinsmen, far], hazards)
        self.assertIn("sh_kinsmen", closer)
        self.assertNotIn("sh_terwillegar", closer)

    def test_mid_trip_pin_nearer_fire_still_uses_original_start(self):
        # Same layout as above. Mid-trip the pin is almost on top of the fire, so
        # Kinsmen is no longer "closer than here" — but against the original start
        # it still must stay rejected (the phone passes ref_lat/ref_lon for this).
        kinsmen = {
            "type": "Feature", "id": "sh_kinsmen",
            "properties": {"name": "Kinsmen Sports Centre"},
            "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
        }
        far = {
            "type": "Feature", "id": "sh_terwillegar",
            "properties": {"name": "Terwillegar Rec Centre"},
            "geometry": {"type": "Point", "coordinates": [-113.595, 53.440]},
        }
        fire = {
            "type": "Feature", "id": "hz_1",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-113.55, 53.515], [-113.54, 53.515], [-113.54, 53.525],
                [-113.55, 53.525], [-113.55, 53.515],
            ]]},
        }
        hazards = {"type": "FeatureCollection", "features": [fire]}
        start_lat, start_lon = 53.52, -113.58
        mid_lat, mid_lon = 53.52, -113.546  # near the fire centroid
        from_here = shelters_closer_to_fire_than_start(
            mid_lat, mid_lon, [kinsmen, far], hazards,
        )
        from_start = shelters_closer_to_fire_than_start(
            start_lat, start_lon, [kinsmen, far], hazards,
        )
        self.assertNotIn("sh_kinsmen", from_here)
        self.assertIn("sh_kinsmen", from_start)


if __name__ == "__main__":
    unittest.main()
