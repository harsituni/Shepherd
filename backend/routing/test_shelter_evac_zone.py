"""Shelters inside the dashboard evacuation buffer must not stay recommended."""

import unittest

from backend.routing.evac_zone import danger_rings, mark_unsafe_shelters, unsafe_shelter_ids
from backend.routing.safety import SHELTER_EVAC_M, RoutePath, judge
from backend.routing.v3_testing import Forecast, grid_around, ll
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

    def test_find_routes_demotes_unsafe_shelter_recommendation(self):
        from backend.routing import router
        from backend.routing.test_find_routes_v3 import FindRoutesV3Tests

        t = FindRoutesV3Tests()
        t.setUp()
        # Paint sh_a inside a fake current-fire evacuation circle.
        lon, lat = t.shelters[0]["geometry"]["coordinates"]
        fire = {
            "type": "Feature", "id": "hz_test",
            "properties": {"kind": "wildfire", "zone": "core"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [lon - 0.002, lat - 0.001], [lon + 0.002, lat - 0.001],
                [lon + 0.002, lat + 0.001], [lon - 0.002, lat + 0.001],
                [lon - 0.002, lat - 0.001],
            ]]},
        }
        body = router.find_routes_v3(
            53.54, -113.50, None, t.shelters,
            hazards={"type": "FeatureCollection", "features": [fire]},
        )
        a = next(o for o in body["options"] if o["shelter_id"] == "sh_a")
        self.assertEqual(a["status"], "blocked")
        self.assertIn("evacuation zone", a["reason"])
        self.assertNotEqual(body.get("shelter_id"), "sh_a")
        if body["best_route_id"]:
            best = next(o for o in body["options"] if o["id"] == body["best_route_id"])
            self.assertNotEqual(best["shelter_id"], "sh_a")
            self.assertIn(best["status"], ("ok", "tight"))


if __name__ == "__main__":
    unittest.main()
