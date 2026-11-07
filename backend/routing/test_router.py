"""Offline tests for Step 1 road routing."""

import inspect
import json
import os
import tempfile

import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import networkx as nx
from shapely.geometry import LineString

from backend.routing import router
from backend.routing.router import NoRouteError, closed_roads, find_route, load_graph


# Small fake road map. Each point is (longitude, latitude).
POINTS = {
    1: (-113.50, 53.54),
    2: (-113.49, 53.54),
    3: (-113.48, 53.54),
    4: (-113.50, 53.55),
    5: (-113.501, 53.541),
}
BEND = (-113.495, 53.542)


def fake_graph():
    """Make a few roads without downloading anything."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for number, (lon, lat) in POINTS.items():
        graph.add_node(number, x=lon, y=lat)

    graph.add_edge(1, 2, length=900.0)
    graph.add_edge(1, 2, length=300.0,
                   geometry=LineString([POINTS[2], BEND, POINTS[1]]))
    graph.add_edge(2, 3, length=400.0)
    graph.add_edge(1, 3, length=2000.0)
    graph.add_edge(1, 4, length=1500.0)
    # Point 5 is not connected to the other roads.
    return graph


def shelter(name, node, is_open=True, capacity=100, occupancy=0):
    """Make a fake shelter at one of the road points."""
    return {
        "type": "Feature",
        "id": name,
        "properties": {
            "name": name,
            "open": is_open,
            "capacity": capacity,
            "occupancy": occupancy,
        },
        "geometry": {
            "type": "Point",
            "coordinates": list(POINTS[node]),
        },
    }


def hazard_box(west, south, east, north, zone="core"):
    """Make a small rectangular fire for testing."""
    return {
        "type": "Feature",
        "properties": {"kind": "wildfire", "zone": zone},
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north],
            [west, north], [west, south],
        ]]},
    }


class RoutingTests(unittest.TestCase):
    def setUp(self):
        # Give the router our small graph, not real Edmonton data.
        self.graph = fake_graph()
        graph_patch = patch.object(router, "_graph", self.graph)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

        # Fail the test if anything tries to download roads.
        download_patch = patch.object(
            router.ox, "graph_from_bbox",
            side_effect=AssertionError("A test tried to download roads"),
        ) 
        download_patch.start()
        self.addCleanup(download_patch.stop)

    def test_fire_uses_longer_road(self):
        # Find the shortest route without fire.
        shelters = [shelter("sh_a", 3)]
        normal = self.route(shelters)

        # Put a fire on the shorter curved road.
        fire = {
            "type": "Feature",
            "properties": {
                "kind": "wildfire",
                "zone": "core"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-113.496, 53.5415],
                    [-113.494, 53.5415],
                    [-113.494, 53.5425],
                    [-113.496, 53.5425],
                    [-113.496, 53.5415]
                ]]
            }
        }

        # Find another route around the fire.
        original_edges = self.graph.number_of_edges()
        detour = find_route(53.54, -113.50, [fire], shelters)

        # The new route should be longer.
        self.assertEqual(normal["distance_km"], 0.7)
        self.assertEqual(detour["distance_km"], 1.3)
        self.assertFalse(normal["rerouted"])
        self.assertIsNone(normal["reroute_reason"])
        self.assertTrue(detour["rerouted"])
        self.assertEqual(detour["reroute_reason"], "Route changed because of a core hazard")

        # Make sure the original roads were not changed.
        self.assertEqual(self.graph.number_of_edges(), original_edges)

    def test_detour_uses_different_nodes(self):
        fire = hazard_box(-113.486, 53.539, -113.484, 53.541)
        self.graph.add_edge(4, 3, length=1000.0,
                            geometry=LineString([POINTS[4], (-113.48, 53.55), POINTS[3]]))
        result = find_route(53.54, -113.50, [fire], [shelter("sh_a", 3)])
        self.assertEqual(result["distance_km"], 2.5)
        self.assertIn(list(POINTS[4]), result["geometry"]["coordinates"])
        self.assertTrue(result["rerouted"])
        self.assertIsInstance(result["reroute_reason"], str)

    def test_unrelated_closed_road_does_not_mean_rerouted(self):
        fire = hazard_box(-113.501, 53.546, -113.499, 53.547)
        self.assertTrue(router._blocked_edges(self.graph, [fire]))
        choices = [shelter("sh_a", 3)]
        self.assertEqual(find_route(53.54, -113.50, [fire], choices), self.route(choices))

    def test_distant_hazard_and_buffer_do_not_change_route(self):
        choices = [shelter("sh_a", 3)]
        for fire in [hazard_box(-113.65, 53.56, -113.64, 53.57),
                     hazard_box(-113.51, 53.53, -113.47, 53.56, zone="buffer")]:
            with self.subTest(fire=fire):
                self.assertEqual(find_route(53.54, -113.50, [fire], choices), self.route(choices))

    def test_hazard_changes_selected_shelter(self):
        fire = hazard_box(-113.486, 53.539, -113.484, 53.541)
        choices = [shelter("sh_a", 3), shelter("sh_b", 4)]
        self.assertEqual(self.route(choices)["shelter_id"], "sh_a")
        result = find_route(53.54, -113.50, [fire], choices)
        self.assertEqual(result["shelter_id"], "sh_b")
        self.assertTrue(result["rerouted"])
        self.assertIsNotNone(result["reroute_reason"])

    def test_all_paths_blocked_with_endpoints_outside_fire(self):
        fire = hazard_box(-113.486, 53.539, -113.484, 53.541)
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [fire], [shelter("sh_a", 3)])

    def test_start_inside_hazard_even_when_road_node_is_outside(self):
        fire = hazard_box(-113.5002, 53.5397, -113.4998, 53.5399)
        with self.assertRaises(NoRouteError):
            find_route(53.5398, -113.50, [fire], [shelter("sh_a", 3)])

    def test_destination_inside_hazard_is_not_selected(self):
        fire = hazard_box(-113.4802, 53.5397, -113.4798, 53.5399)
        destination = shelter("sh_a", 3)
        destination["geometry"]["coordinates"] = [-113.48, 53.5398]
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [fire], [destination])

    def test_same_node_inside_hazard_is_not_a_zero_distance_route(self):
        fire = hazard_box(-113.501, 53.539, -113.499, 53.541)
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [fire], [shelter("sh_here", 1)])

    def test_snapping_connection_cannot_cross_hazard(self):
        # The point and node are outside, but the gap between them crosses fire.
        start_fire = hazard_box(-113.5002, 53.5394, -113.4998, 53.5396)
        with self.assertRaises(NoRouteError):
            find_route(53.539, -113.50, [start_fire], [shelter("sh_a", 3)])
        end_fire = hazard_box(-113.4802, 53.5394, -113.4798, 53.5396)
        destination = shelter("sh_a", 3)
        destination["geometry"]["coordinates"] = [-113.48, 53.539]
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [end_fire], [destination])

    def test_closure_does_not_snap_to_a_different_road(self):
        fire = hazard_box(-113.486, 53.539, -113.484, 53.541)
        # Node 2 loses all outgoing roads, but node 3 still has a route.
        self.graph.add_edge(3, 4, length=1000.0)
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.49, [fire], [shelter("sh_a", 4)])

    def test_successful_detour_preserves_inputs_and_entire_graph(self):
        hazards = [hazard_box(-113.496, 53.5415, -113.494, 53.5425)]
        choices = [shelter("sh_a", 3)]
        original_inputs = deepcopy((hazards, choices))
        original_graph = deepcopy(self.graph)
        normal = self.route(choices)
        result = find_route(53.54, -113.50, hazards, choices)
        self.assertTrue(result["rerouted"])
        self.assertEqual((hazards, choices), original_inputs)
        self.assertTrue(nx.utils.graphs_equal(self.graph, original_graph))
        self.assertEqual(self.route(choices), normal)

    def route(self, shelters):
        return find_route(53.54, -113.50, [], shelters)

    def test_nearest_reachable_by_road_length(self):
        choices = [
            shelter("sh_disconnected", 5),
            shelter("sh_long_road", 4),
            shelter("sh_short_road", 3),
        ]
        result = self.route(choices)
        self.assertEqual(result["shelter_id"], "sh_short_road")
        self.assertEqual(result["distance_km"], 0.7)

    def test_curved_roads_and_shorter_parallel_road(self):
        result = self.route([shelter("sh_a", 3)])
        self.assertEqual(result["geometry"], {
            "type": "LineString",
            "coordinates": [
                list(POINTS[1]), list(BEND), list(POINTS[2]), list(POINTS[3])
            ],
        })
        self.assertEqual(result["distance_km"], 0.7)
        self.assertEqual(result["eta_min"], 2)

    def test_response_format(self):
        result = self.route([shelter("sh_a", 3)])
        self.assertEqual(set(result), {
            "shelter_id", "shelter_name", "distance_km", "eta_min",
            "rerouted", "reroute_reason", "steps", "geometry",
        })
        self.assertEqual(result["shelter_name"], "sh_a")
        self.assertIsInstance(result["distance_km"], float)
        self.assertIsInstance(result["eta_min"], int)
        self.assertFalse(result["rerouted"])
        self.assertIsNone(result["reroute_reason"])
        self.assertEqual(result["steps"], [])
        json.dumps(result, allow_nan=False)

    def test_closed_full_and_overfull_shelters(self):
        choices = [
            shelter("sh_closed", 2, is_open=False),
            shelter("sh_full", 2, occupancy=100),
            shelter("sh_overfull", 2, occupancy=101),
            shelter("sh_available", 3, occupancy=99),
        ]
        self.assertEqual(self.route(choices)["shelter_id"], "sh_available")

    def test_no_eligible_or_reachable_shelters(self):
        cases = [
            [],
            [shelter("sh_closed", 2, is_open=False)],
            [shelter("sh_full", 2, occupancy=100)],
            [shelter("sh_zero", 2, capacity=0)],
            [shelter("sh_unreachable", 5)],
        ]
        for choices in cases:
            with self.subTest(choices=choices):
                with self.assertRaises(NoRouteError):
                    self.route(choices)

    def test_one_way_roads(self):
        # Roads go from 1 to 3, but not backwards from 3 to 1.
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.48, [], [shelter("sh_start", 1)])

    def test_same_node_is_zero_distance(self):
        result = self.route([shelter("sh_here", 1)])
        self.assertEqual(result["distance_km"], 0.0)
        self.assertEqual(result["eta_min"], 0)
        self.assertEqual(result["geometry"]["coordinates"], [
            list(POINTS[1]), list(POINTS[1])
        ])

    def test_locations_snap_to_roads(self):
        destination = shelter("sh_a", 3)
        destination["geometry"]["coordinates"] = [-113.47999, 53.54001]
        result = find_route(53.54001, -113.50001, [], [destination])
        self.assertEqual(result["geometry"]["coordinates"][0], list(POINTS[1]))
        self.assertEqual(result["geometry"]["coordinates"][-1], list(POINTS[3]))

    def test_ties_keep_first_shelter(self):
        result = self.route([shelter("sh_a", 3), shelter("sh_b", 3)])
        self.assertEqual(result["shelter_id"], "sh_a")

    def test_no_route_when_fire_blocks_roads(self):
        hazards = [{
            "type": "Feature",
            "id": "hz_1",
            "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-113.51, 53.53], [-113.47, 53.53], [-113.47, 53.56],
                [-113.51, 53.56], [-113.51, 53.53],
            ]]},
            }]
        shelters = [shelter("sh_a", 3)]
        original = deepcopy((hazards, shelters))
        # The fire blocks all roads, so there is no route.
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, hazards, shelters)

        self.assertEqual(closed_roads(hazards), [])
        self.assertEqual((hazards, shelters), original)

    def test_outside_demo_area(self):
        with self.assertRaises(NoRouteError):
            find_route(0, 0, [], [shelter("sh_a", 3)])
        outside = shelter("sh_outside", 3)
        outside["geometry"]["coordinates"] = [0, 0]
        with self.assertRaises(NoRouteError):
            self.route([outside])

    def test_graph_must_be_loaded(self):
        with patch.object(router, "_graph", None):
            with self.assertRaisesRegex(RuntimeError, "load_graph"):
                self.route([shelter("sh_a", 3)])
        with patch.object(router, "_graph", nx.MultiDiGraph()):
            with self.assertRaises(NoRouteError):
                self.route([shelter("sh_a", 3)])

    def test_function_names_stay_the_same(self):
        self.assertTrue(issubclass(NoRouteError, Exception))
        self.assertEqual(list(inspect.signature(load_graph).parameters), [])
        self.assertEqual(list(inspect.signature(find_route).parameters), [
            "lat", "lon", "hazards", "shelters",
        ])
        self.assertEqual(list(inspect.signature(closed_roads).parameters), ["hazards"])


class GraphLoadingTests(unittest.TestCase):
    def setUp(self):
        backup_patch = patch.object(router, "_backup_mode", False)
        backup_patch.start()
        self.addCleanup(backup_patch.stop)
        env_patch = patch.dict(os.environ)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("SHEPHERD_GRAPH_PATH", None)

        graph_patch = patch.object(router, "_graph", None)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

        download_patch = patch.object(
            router.ox, "graph_from_bbox",
            side_effect=AssertionError("A test tried to download roads"),
        )
        self.download = download_patch.start()
        self.addCleanup(download_patch.stop)

    def test_environment_path_loads_saved_graph_once(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "saved roads.graphml"
            router.ox.save_graphml(fake_graph(), saved_file)
            os.environ["SHEPHERD_GRAPH_PATH"] = str(saved_file)
            with patch.object(router.ox, "load_graphml", wraps=router.ox.load_graphml) as load:
                load_graph()
                load_graph()
                load.assert_called_once_with(saved_file)
            result = find_route(53.54, -113.50, [], [shelter("sh_a", 3)])
            self.assertEqual(result["distance_km"], 0.7)
            self.assertIn(list(BEND), result["geometry"]["coordinates"])
            self.download.assert_not_called()

    def test_missing_environment_path_enables_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "missing.graphml"
            os.environ["SHEPHERD_GRAPH_PATH"] = str(saved_file)
            with self.assertLogs(router.__name__, level="WARNING") as logs:
                load_graph()
            self.assertIn(str(saved_file), logs.output[0])
            self.assertIn("not navigation instructions", logs.output[0])
            self.assertTrue(router._backup_mode)
            self.assertIsNone(router._graph)
            self.assertFalse(saved_file.exists())
            result = find_route(53.54, -113.50, [], [shelter("sh_a", 3)])
            self.assertTrue(result["approximate"])
            self.download.assert_not_called()

    def test_environment_path_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for saved_path in [folder, ""]:
                with self.subTest(saved_path=saved_path):
                    os.environ["SHEPHERD_GRAPH_PATH"] = saved_path
                    router._backup_mode = False
                    with self.assertLogs(router.__name__, level="WARNING"):
                        load_graph()
                    self.assertTrue(router._backup_mode)
                    self.assertIsNone(router._graph)
            self.download.assert_not_called()

    def test_environment_file_error_does_not_download(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            saved_file.touch()
            os.environ["SHEPHERD_GRAPH_PATH"] = str(saved_file)
            # Real malformed XML must also enter backup mode.
            with self.assertLogs(router.__name__, level="WARNING"):
                load_graph()
            self.assertTrue(router._backup_mode)
            self.assertIsNone(router._graph)
            self.download.assert_not_called()

    def test_default_saved_file_loads_once_without_download(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            router.ox.save_graphml(fake_graph(), saved_file)
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router.ox, "load_graphml", wraps=router.ox.load_graphml) as load:
                load_graph()
                load_graph()
                load.assert_called_once_with(saved_file)
                router._graph = None
                load_graph()
                self.assertEqual(load.call_count, 2)
                result = find_route(53.54, -113.50, [], [shelter("sh_a", 3)])
                self.assertEqual(result["distance_km"], 0.7)
                self.assertIn(list(BEND), result["geometry"]["coordinates"])
                self.assertNotIn("approximate", result)
            self.download.assert_not_called()

    def test_missing_default_file_never_downloads_or_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router.ox, "load_graphml") as load:
                with self.assertLogs(router.__name__, level="WARNING") as logs:
                    load_graph()
                    load_graph()
                self.assertEqual(len(logs.output), 1)
                load.assert_not_called()
                self.download.assert_not_called()
                self.assertTrue(router._backup_mode)
                self.assertIsNone(router._graph)
                self.assertFalse(saved_file.exists())

    def test_unreadable_file_enables_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            saved_file.touch()
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router.ox, "load_graphml", side_effect=PermissionError("denied")):
                with self.assertLogs(router.__name__, level="WARNING"):
                    load_graph()
                self.assertTrue(router._backup_mode)
                self.download.assert_not_called()

    def test_empty_saved_graph_enables_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            router.ox.save_graphml(nx.MultiDiGraph(crs="EPSG:4326"), saved_file)
            with patch.object(router, "GRAPH_PATH", saved_file):
                with self.assertLogs(router.__name__, level="WARNING"):
                    load_graph()
                self.assertTrue(router._backup_mode)


class BackupTests(unittest.TestCase):
    def setUp(self):
        for name, value in [("_graph", None), ("_backup_mode", True)]:
            setting = patch.object(router, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        blocked = patch.object(router.ox, "graph_from_bbox", side_effect=AssertionError("No downloads"))
        blocked.start()
        self.addCleanup(blocked.stop)

    def test_nearest_eligible_shelter_and_estimate_fields(self):
        choices = [shelter("sh_closed", 1, is_open=False),
                   shelter("sh_full", 1, occupancy=100),
                   shelter("sh_overfull", 1, occupancy=101),
                   shelter("sh_far", 3), shelter("sh_near", 2)]
        original = deepcopy(choices)
        result = find_route(53.54, -113.50, [], choices)
        self.assertEqual(result["shelter_id"], "sh_near")
        self.assertEqual(result["geometry"]["coordinates"], [list(POINTS[1]), list(POINTS[2])])
        self.assertEqual(result["distance_km"], 0.7)
        self.assertEqual(result["eta_min"], 2)
        self.assertTrue(result["approximate"])
        self.assertIn("not navigation instructions", result["warning"])
        self.assertEqual(result["steps"], [])
        self.assertFalse(result["rerouted"])
        self.assertIsNone(result["reroute_reason"])
        self.assertEqual(choices, original)
        json.dumps(result, allow_nan=False)

    def test_blocked_nearest_line_selects_clear_shelter(self):
        fire = hazard_box(-113.496, 53.539, -113.494, 53.541)
        result = find_route(53.54, -113.50, [fire], [shelter("sh_near", 2), shelter("sh_clear", 4)])
        self.assertEqual(result["shelter_id"], "sh_clear")

    def test_crossing_touching_and_endpoint_hazards_are_rejected(self):
        fires = [hazard_box(-113.496, 53.539, -113.494, 53.541),
                 hazard_box(-113.496, 53.540, -113.494, 53.541),
                 hazard_box(-113.501, 53.539, -113.499, 53.541),
                 hazard_box(-113.491, 53.539, -113.489, 53.541)]
        for fire in fires:
            with self.subTest(fire=fire), self.assertRaises(NoRouteError):
                find_route(53.54, -113.50, [fire], [shelter("sh_a", 2)])

    def test_same_location_is_rejected_inside_fire(self):
        fire = hazard_box(-113.501, 53.539, -113.499, 53.541)
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [fire], [shelter("sh_here", 1)])
        result = find_route(53.54, -113.50, [], [shelter("sh_here", 1)])
        self.assertEqual(result["distance_km"], 0)

    def test_no_eligible_shelter_raises(self):
        for choices in [[], [shelter("sh_closed", 2, is_open=False)],
                        [shelter("sh_full", 2, occupancy=100)]]:
            with self.subTest(choices=choices), self.assertRaises(NoRouteError):
                find_route(53.54, -113.50, [], choices)

    def test_demo_bounds_still_apply(self):
        with self.assertRaises(NoRouteError):
            find_route(0, 0, [], [shelter("sh_a", 2)])
        outside = shelter("sh_outside", 2)
        outside["geometry"]["coordinates"] = [0, 0]
        with self.assertRaises(NoRouteError):
            find_route(53.54, -113.50, [], [outside])

    def test_buffer_is_not_a_core_closure(self):
        fire = hazard_box(-113.51, 53.53, -113.47, 53.56, zone="buffer")
        result = find_route(53.54, -113.50, [fire], [shelter("sh_a", 2)])
        self.assertTrue(result["approximate"])

    def test_loaded_disconnected_roads_do_not_use_backup(self):
        with patch.object(router, "_graph", fake_graph()):
            with self.assertRaises(NoRouteError):
                find_route(53.54, -113.50, [], [shelter("sh_disconnected", 5)])


if __name__ == "__main__":
    unittest.main()
