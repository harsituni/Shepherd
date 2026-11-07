import inspect
import json
import unittest
from copy import deepcopy

from router import NoRouteError, closed_roads, find_route, load_graph


def shelter(name, lon, lat, is_open=True, capacity=100, occupancy=0):
    return {
        "type": "Feature",
        "id": name,
        "properties": {
            "name": name,
            "open": is_open,
            "capacity": capacity,
            "occupancy": occupancy,
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


class RoutingTests(unittest.TestCase):
    def test_response_schema_and_coordinate_order(self):
        shelters = [shelter("sh_a", -113.516, 53.519)]
        result = find_route(53.52, -113.62, [], shelters)

        expected = {
            "shelter_id",
            "shelter_name",
            "distance_km",
            "eta_min",
            "rerouted",
            "reroute_reason",
            "steps",
            "geometry",
        }
        self.assertEqual(set(result.keys()), expected)
        self.assertEqual(result["shelter_id"], "sh_a")
        self.assertEqual(result["shelter_name"], "sh_a")
        self.assertIsInstance(result["distance_km"], float)
        self.assertEqual(result["distance_km"], round(result["distance_km"], 1))
        self.assertIsInstance(result["eta_min"], int)
        self.assertEqual(result["rerouted"], False)
        self.assertIsNone(result["reroute_reason"])
        self.assertEqual(result["steps"], [])
        self.assertEqual(
            result["geometry"],
            {
                "type": "LineString",
                "coordinates": [[-113.62, 53.52], [-113.516, 53.519]],
            },
        )
        json.dumps(result, allow_nan=False)

    def test_known_haversine_distance_and_contract_eta(self):
        shelters = [shelter("sh_a", 1, 0)]
        result = find_route(0, 0, [], shelters)
        # ~111.2 km at equator for 1° lon; contract: 1 decimal + eta @ 40 km/h
        self.assertEqual(result["distance_km"], 111.2)
        self.assertEqual(result["eta_min"], round(111.2 / 40 * 60))

    def test_nearest_uses_haversine_not_coordinate_distance(self):
        shelters = [
            shelter("sh_north", 0, 81),
            shelter("sh_east", 2, 80),
        ]
        result = find_route(80, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_east")

    def test_closed_shelters_are_ineligible(self):
        shelters = [
            shelter("sh_closed", 0, 0, is_open=False),
            shelter("sh_available", 1, 0),
        ]
        result = find_route(0, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_available")

    def test_no_eligible_shelter(self):
        cases = [
            [],
            [shelter("sh_closed", 0, 0, is_open=False)],
        ]
        for shelters in cases:
            with self.assertRaises(NoRouteError):
                find_route(0, 0, [], shelters)

    def test_same_location_has_zero_distance_and_eta(self):
        shelters = [shelter("sh_a", -113, 53)]
        result = find_route(53, -113, [], shelters)
        self.assertEqual(result["distance_km"], 0.0)
        self.assertEqual(result["eta_min"], 0)
        self.assertEqual(result["geometry"]["coordinates"], [[-113, 53], [-113, 53]])

    def test_ties_keep_first_shelter(self):
        shelters = [shelter("sh_a", 1, 0), shelter("sh_b", -1, 0)]
        result = find_route(0, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_a")

    def test_hazards_are_accepted_ignored_and_inputs_unchanged(self):
        hazards = [
            {
                "type": "Feature",
                "id": "hz_1",
                "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-1, -1], [2, -1], [2, 1], [-1, 1], [-1, -1]]],
                },
            }
        ]
        shelters = [shelter("sh_a", 1, 0)]
        original = deepcopy((hazards, shelters))
        with_hazard = find_route(0, 0, hazards, shelters)
        without_hazard = find_route(0, 0, [], shelters)
        self.assertEqual(with_hazard, without_hazard)
        self.assertEqual(closed_roads(hazards), [])
        self.assertEqual((hazards, shelters), original)

    def test_placeholders(self):
        self.assertIsNone(load_graph())
        self.assertEqual(closed_roads([]), [])

    def test_contract_signatures(self):
        self.assertTrue(issubclass(NoRouteError, Exception))
        self.assertEqual(list(inspect.signature(load_graph).parameters), [])
        self.assertEqual(
            list(inspect.signature(find_route).parameters),
            ["lat", "lon", "hazards", "shelters"],
        )
        self.assertEqual(
            list(inspect.signature(closed_roads).parameters),
            ["hazards"],
        )


if __name__ == "__main__":
    unittest.main()
