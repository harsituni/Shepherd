
import unittest
import json
import inspect
from copy import deepcopy
from math import ceil

from router import NoRouteError, find_route, load_graph, closed_roads


"""Makes a fake shelter for testing"""
def shelter(name, lon, lat, is_open=True, capacity=100, occupancy=0):
    return {
        "type": "Feature",
        "id": name,
        "properties": {
            "name": name,
            "open": is_open,
            "capacity": capacity,
            "occupancy": occupancy
        },
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat]
        }
    }


class RoutingTests(unittest.TestCase):

    """"Checks if the route has the right information"""
    def test_response_schema_and_coordinate_order(self):
        shelters = [shelter("sh_a", -113.516, 53.519)]
        result = find_route(53.52, -113.62, [], shelters)

        expected = {
            "shelter_id", "shelter_name", "distance_km",
            "eta_min", "rerouted", "reroute_reason",
            "steps", "geometry"
        }

        self.assertEqual(set(result.keys()), expected)
        self.assertEqual(result["shelter_id"], "sh_a")
        self.assertEqual(result["shelter_name"], "sh_a")
        self.assertIsInstance(result["distance_km"], float)
        self.assertIsInstance(result["eta_min"], int)
        self.assertEqual(result["rerouted"], False)
        self.assertIsNone(result["reroute_reason"])
        self.assertEqual(result["steps"], [])

        expected_route = {
            "type": "LineString",
            "coordinates": [
                [-113.62, 53.52],
                [-113.516, 53.519]
            ]
        }

        self.assertEqual(result["geometry"], expected_route)
        json.dumps(result, allow_nan=False)

    """"Checks the distance and estimated time."""
    def test_known_haversine_distance_and_illustrative_eta(self):
        shelters = [shelter("sh_a", 1, 0)]
        result = find_route(0, 0, [], shelters)

        self.assertAlmostEqual(result["distance_km"], 111.195, places=3)
        self.assertEqual(result["eta_min"], ceil(111.195 / 5 * 60))

    """Checks if the nearest shelter is selected"""
    def test_nearest_uses_haversine_not_coordinate_distance(self):
        shelters = [
            shelter("sh_north", 0, 81),
            shelter("sh_east", 2, 80)
        ]

        result = find_route(80, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_east")

    """Checks the distance and estimated time"""
    def test_closed_full_and_overfull_shelters_are_ineligible(self):
        shelters = [
            shelter("sh_closed", 0, 0, is_open=False),
            shelter("sh_full", 0.01, 0, occupancy=100),
            shelter("sh_overfull", 0.02, 0, occupancy=101),
            shelter("sh_available", 1, 0, occupancy=99)
        ]

        result = find_route(0, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_available")

    """Checks if an error happens when no shelters are available"""
    def test_no_eligible_shelter(self):
        cases = [
            [],
            [shelter("sh_closed", 0, 0, is_open=False)],
            [shelter("sh_full", 0, 0, occupancy=100)],
            [shelter("sh_zero", 0, 0, capacity=0)]
        ]

        for shelters in cases:
            with self.assertRaises(NoRouteError):
                find_route(0, 0, [], shelters)

    """"Checks if distance is zero when already at the shelter"""
    def test_same_location_has_zero_distance_and_eta(self):
        shelters = [shelter("sh_a", -113, 53)]
        result = find_route(53, -113, [], shelters)

        self.assertEqual(result["distance_km"], 0)
        self.assertEqual(result["eta_min"], 0)
        self.assertEqual(
            result["geometry"]["coordinates"],
            [[-113, 53], [-113, 53]]
        )

    """Checks if the first shelter is picked when distances tie"""
    def test_ties_keep_first_shelter(self):
        shelters = [
            shelter("sh_a", 1, 0),
            shelter("sh_b", -1, 0)
        ]

        result = find_route(0, 0, [], shelters)
        self.assertEqual(result["shelter_id"], "sh_a")

    """Checks that hazards are ignored for now"""
    def test_hazards_are_accepted_ignored_and_inputs_unchanged(self):
        hazards = [{
            "type": "Feature",
            "id": "hz_1",
            "properties": {
                "kind": "wildfire",
                "zone": "core",
                "source": "sim"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-1, -1], [2, -1], [2, 1],
                    [-1, 1], [-1, -1]
                ]]
            }
        }]

        shelters = [shelter("sh_a", 1, 0)]
        original = deepcopy((hazards, shelters))

        with_hazard = find_route(0, 0, hazards, shelters)
        without_hazard = find_route(0, 0, [], shelters)

        self.assertEqual(with_hazard, without_hazard)
        self.assertEqual(closed_roads(hazards), [])
        self.assertEqual((hazards, shelters), original)

    """Checks the functions we will finish later"""
    def test_placeholders(self):
        self.assertIsNone(load_graph())
        self.assertEqual(closed_roads([]), [])

    """Checks that our functions match the team contract"""
    def test_contract_signatures(self):
        self.assertTrue(issubclass(NoRouteError, Exception))

        self.assertEqual(
            str(inspect.signature(load_graph)),
            "() -> None"
        )

        self.assertEqual(
            str(inspect.signature(find_route)),
            "(lat: float, lon: float, hazards: list[dict], shelters: list[dict]) -> dict"
        )

        self.assertEqual(
            str(inspect.signature(closed_roads)),
            "(hazards: list[dict]) -> list[dict]"
        )


if __name__ == "__main__":
    unittest.main()
