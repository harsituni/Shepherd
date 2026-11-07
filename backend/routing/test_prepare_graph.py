"""Offline checks for manual road preparation."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import networkx as nx

from backend.routing import prepare_graph, router


def demo_graph():
    # Small test roads, not replacement Edmonton data.
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for number, (lon, lat) in enumerate(prepare_graph.LOCATIONS.values()):
        graph.add_node(number, x=lon, y=lat)
    for start in graph.nodes:
        for end in graph.nodes:
            if start != end:
                graph.add_edge(start, end, length=1000.0)
    return graph


class PrepareGraphTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "roads.graphml"
        self.graph = demo_graph()
        download_patch = patch.object(
            prepare_graph.ox, "graph_from_bbox",
            side_effect=AssertionError("A test tried to download roads"),
        )
        self.download = download_patch.start()
        self.addCleanup(download_patch.stop)
        print_patch = patch("builtins.print")
        print_patch.start()
        self.addCleanup(print_patch.stop)
        for name in ["cache_folder", "use_cache", "max_query_area_size",
                     "overpass_rate_limit", "requests_timeout", "log_console"]:
            setting_patch = patch.object(prepare_graph.ox.settings, name)
            setting_patch.start()
            self.addCleanup(setting_patch.stop)

    def test_missing_file_never_downloads_by_default(self):
        with self.assertRaisesRegex(FileNotFoundError, "--download"):
            prepare_graph.prepare_graph(self.path)
        self.download.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_saved_file_is_reused_even_with_download_flag(self):
        prepare_graph.ox.save_graphml(self.graph, self.path)
        original = self.path.read_bytes()
        for download in [False, True]:
            prepare_graph.prepare_graph(self.path, download)
        self.download.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)

    def test_explicit_download_saves_graph_for_router(self):
        self.download.side_effect = None
        self.download.return_value = self.graph
        prepare_graph.prepare_graph(self.path, download=True)
        self.download.assert_called_once_with(
            router.DEMO_BBOX, network_type="drive", retain_all=True
        )
        self.assertEqual(prepare_graph.ox.settings.max_query_area_size, 25_000_000)
        self.assertTrue(prepare_graph.ox.settings.use_cache)
        self.assertTrue(prepare_graph.ox.settings.overpass_rate_limit)
        self.assertEqual(prepare_graph.ox.settings.requests_timeout, 120)
        with patch.dict(os.environ, {"SHEPHERD_GRAPH_PATH": str(self.path)}), \
             patch.object(router, "_graph", None):
            router.load_graph()
            self.assertEqual(len(router._graph), 4)
            prepare_graph.check_graph(router._graph)

    def test_empty_graph_fails(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            prepare_graph.check_graph(nx.MultiDiGraph())

    def test_small_graph_does_not_count_as_coverage(self):
        for node in self.graph.nodes:
            self.graph.nodes[node]["x"] = -113.51
            self.graph.nodes[node]["y"] = 53.54
        with self.assertRaisesRegex(ValueError, "cover all four"):
            prepare_graph.check_graph(self.graph)

    def test_far_road_nodes_fail_even_inside_bounds(self):
        for node, point in enumerate([(-113.70, 53.42), (-113.70, 53.58),
                                      (-113.43, 53.42), (-113.43, 53.58)]):
            self.graph.nodes[node]["x"], self.graph.nodes[node]["y"] = point
        with self.assertRaisesRegex(ValueError, "cover all four"):
            prepare_graph.check_graph(self.graph)

    def test_one_way_disconnection_fails(self):
        self.graph.remove_edges_from(list(self.graph.out_edges(0, keys=True)))
        with self.assertRaisesRegex(ValueError, "No road route from Kinsmen"):
            prepare_graph.check_graph(self.graph)

    def test_failed_download_does_not_save(self):
        self.download.side_effect = ConnectionError("offline")
        with self.assertRaisesRegex(ConnectionError, "offline"):
            prepare_graph.prepare_graph(self.path, download=True)
        self.assertFalse(self.path.exists())

    def test_failed_connectivity_check_keeps_saved_graph(self):
        self.download.side_effect = None
        self.graph.remove_edges_from(list(self.graph.out_edges(0, keys=True)))
        self.download.return_value = self.graph
        with self.assertRaisesRegex(ValueError, "Graph saved.*did not pass validation") as error:
            prepare_graph.prepare_graph(self.path, download=True)
        self.assertIn(str(self.path), str(error.exception))
        self.assertIn("No road route from Kinsmen", str(error.exception))
        self.assertIn("kept for offline inspection", str(error.exception))
        saved_graph = prepare_graph.ox.load_graphml(self.path)
        self.assertTrue(nx.utils.graphs_equal(saved_graph, self.graph))
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "No road route from Kinsmen"):
            prepare_graph.prepare_graph(self.path, download=True)
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_coverage_check_keeps_saved_graph(self):
        self.download.side_effect = None
        for node in self.graph.nodes:
            self.graph.nodes[node]["x"] = -113.51
            self.graph.nodes[node]["y"] = 53.54
        self.download.return_value = self.graph
        with self.assertRaisesRegex(ValueError, "Graph saved.*cover all four"):
            prepare_graph.prepare_graph(self.path, download=True)
        saved_graph = prepare_graph.ox.load_graphml(self.path)
        self.assertTrue(nx.utils.graphs_equal(saved_graph, self.graph))

    def test_save_error_stops_before_validation(self):
        self.download.side_effect = None
        self.download.return_value = self.graph
        with patch.object(prepare_graph.ox, "save_graphml", side_effect=OSError("disk full")), \
             patch.object(prepare_graph, "check_graph") as check:
            with self.assertRaisesRegex(OSError, "disk full"):
                prepare_graph.prepare_graph(self.path, download=True)
            check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
