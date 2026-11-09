"""load_graph: the saved Edmonton road map, never a download; backup mode when it can't load."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from backend.routing import router
from backend.routing.router import find_routes, load_graph
from backend.routing.tests.helpers import BEND, POINTS, fake_graph, shelter


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
        router.forget_road_graph()
        self.addCleanup(router.forget_road_graph)

    def assert_routes_on_roads(self):
        body = find_routes(53.54, -113.50, None, [shelter("sh_a", POINTS[3])])
        self.assertFalse(body["approximate"])
        self.assertEqual(body["distance_km"], 0.7)
        self.assertIn(list(BEND), body["geometry"]["coordinates"])

    def test_environment_path_loads_saved_graph_once(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "saved roads.graphml"
            router.ox.save_graphml(fake_graph(), saved_file)
            os.environ["SHEPHERD_GRAPH_PATH"] = str(saved_file)
            with patch.object(router.ox, "load_graphml", wraps=router.ox.load_graphml) as load:
                load_graph()
                load_graph()
                load.assert_called_once_with(saved_file)
            self.assert_routes_on_roads()
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
            body = find_routes(53.54, -113.50, None, [shelter("sh_a", POINTS[3])])
            self.assertEqual(body["route_status"], "indeterminate")
            self.assertTrue(body["options"][0]["approximate"])
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
                self.assert_routes_on_roads()
            self.download.assert_not_called()

    def test_missing_default_file_never_downloads_or_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            saved_file = Path(folder) / "roads.graphml"
            missing_gz = Path(folder) / "roads.graphml.gz"
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router, "GRAPH_GZ_PATH", missing_gz), \
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
            missing_gz = Path(folder) / "roads.graphml.gz"
            with patch.object(router, "GRAPH_PATH", saved_file), \
                 patch.object(router, "GRAPH_GZ_PATH", missing_gz), \
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
