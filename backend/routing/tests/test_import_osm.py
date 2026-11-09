"""Tiny offline XML fixtures, never the downloaded Edmonton extract."""

import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from backend.routing import router
from backend.routing.tools import import_osm


XML = b'''<osm version="0.6">
<node id="1" lat="53.54" lon="-113.50"/>
<node id="2" lat="53.54" lon="-113.49"/>
<node id="3" lat="53.55" lon="-113.49"/>
<node id="4" lat="53.55" lon="-113.50"/>
<node id="5" lat="53.56" lon="-113.50"/>
<node id="99" lat="53.54" lon="-113.48"/>
<way id="10"><nd ref="1"/><nd ref="2"/>
<tag k="highway" v="residential"/><tag k="oneway" v="yes"/></way>
<way id="11"><nd ref="2"/><nd ref="3"/>
<tag k="highway" v="primary"/><tag k="oneway" v="-1"/></way>
<way id="12"><nd ref="3"/><nd ref="4"/>
<tag k="highway" v="secondary"/></way>
<way id="13"><nd ref="4"/><nd ref="5"/>
<tag k="highway" v="tertiary"/><tag k="junction" v="roundabout"/></way>
<way id="14"><nd ref="1"/><nd ref="99"/>
<tag k="highway" v="footway"/></way>
<relation id="100"><member type="way" ref="10" role=""/></relation>
</osm>'''


class ImportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source = Path(folder.name) / "tiny.osm.gz"
        self.output = Path(folder.name) / "roads.graphml"
        with gzip.open(self.source, "wb") as saved:
            saved.write(XML)
        for target in ["requests.sessions.Session.request", "osmnx.graph_from_bbox"]:
            blocked = patch(target, side_effect=AssertionError("Network access is forbidden"))
            blocked.start()
            self.addCleanup(blocked.stop)
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_driving_filter(self):
        for road in import_osm.DRIVING_ROADS:
            way = ET.fromstring(f'<way><tag k="highway" v="{road}"/></way>')
            self.assertTrue(import_osm.is_driving_road(way))
        for road in ["footway", "cycleway", "path", "pedestrian", "steps", "construction", "service", "track"]:
            way = ET.fromstring(f'<way><tag k="highway" v="{road}"/></way>')
            self.assertFalse(import_osm.is_driving_road(way))
        for key, value in [("access", "private"), ("access", "no"), ("vehicle", "no"),
                           ("motor_vehicle", "no"), ("motorcar", "no"),
                           ("area", "yes"), ("service", "driveway")]:
            way = ET.fromstring(
                f'<way><tag k="highway" v="residential"/><tag k="{key}" v="{value}"/></way>'
            )
            self.assertFalse(import_osm.is_driving_road(way))

    def test_import_preserves_roads_lengths_and_original(self):
        original = self.source.read_bytes()
        with patch.object(import_osm, "check_graph") as check:
            import_osm.import_graph(self.source, self.output)
            check.assert_called_once()
        graph = import_osm.ox.load_graphml(self.output)
        self.assertEqual(set(graph.nodes), {1, 2, 3, 4, 5})
        self.assertEqual(set(graph.edges()), {(1, 2), (3, 2), (3, 4), (4, 3), (4, 5)})
        self.assertGreater(graph[1][2][0]["length"], 600)
        self.assertLess(graph[1][2][0]["length"], 700)
        for start, end, data in graph.edges(data=True):
            self.assertGreater(data["length"], 0)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(list(self.output.parent.glob("osm_import_*")), [])
        with patch.dict("os.environ", {"SHEPHERD_GRAPH_PATH": str(self.output)}), \
             patch.object(router, "_graph", None):
            router.load_graph()
            self.assertEqual(len(router._graph), 5)

    def test_validation_failure_keeps_graph(self):
        with self.assertRaisesRegex(ValueError, "Graph saved.*did not pass validation"):
            import_osm.import_graph(self.source, self.output)
        self.assertEqual(len(import_osm.ox.load_graphml(self.output)), 5)

    def test_existing_output_is_not_overwritten(self):
        self.output.write_text("keep me")
        with self.assertRaises(FileExistsError):
            import_osm.import_graph(self.source, self.output)
        self.assertEqual(self.output.read_text(), "keep me")

    def test_source_cannot_be_used_as_output(self):
        original = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            import_osm.import_graph(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), original)

    def test_missing_source_fails_without_output(self):
        with self.assertRaises(FileNotFoundError):
            import_osm.import_graph(self.source.parent / "missing.osm.gz", self.output)
        self.assertFalse(self.output.exists())

    def test_missing_referenced_node_fails(self):
        with gzip.open(self.source, "wb") as saved:
            saved.write(XML.replace(b'<node id="1" lat="53.54" lon="-113.50"/>', b""))
        with self.assertRaisesRegex(ValueError, "missing nodes"):
            import_osm.import_graph(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_empty_road_selection_fails(self):
        with gzip.open(self.source, "wb") as saved:
            saved.write(b'<osm version="0.6"><node id="1" lat="53.54" lon="-113.50"/></osm>')
        with self.assertRaisesRegex(ValueError, "No driving roads"):
            import_osm.import_graph(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_memory_guards_stop_before_graph_loading(self):
        for setting in ["MAX_ROAD_NODES", "MAX_XML_BYTES"]:
            with self.subTest(setting=setting), patch.object(import_osm, setting, 1), \
                 patch.object(import_osm.ox, "graph_from_xml") as load:
                with self.assertRaisesRegex(ValueError, "memory guard"):
                    import_osm.import_graph(self.source, self.output)
                load.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.output.parent.glob("osm_import_*")), [])

    def test_explicit_guards_and_separate_output_preserve_old_map(self):
        old_map = self.output.parent / "edmonton_demo_drive.graphml"
        old_map.write_bytes(b"existing map must stay unchanged")
        original = self.source.read_bytes()
        with patch.object(import_osm, "check_graph"), \
             patch.object(import_osm, "MAX_ROAD_NODES", 1), \
             patch.object(import_osm, "MAX_XML_BYTES", 1):
            import_osm.import_graph(self.source, self.output, 10, 10000)
        self.assertEqual(old_map.read_bytes(), b"existing map must stay unchanged")
        self.assertEqual(self.source.read_bytes(), original)
        graph = import_osm.ox.load_graphml(self.output)
        self.assertEqual(set(graph.edges()), {(1, 2), (3, 2), (3, 4), (4, 3), (4, 5)})

    def test_explicit_guards_stop_before_graph_loading(self):
        for nodes, size in [(1, 10000), (10, 1), (0, 10000), (10, -1)]:
            with self.subTest(nodes=nodes, size=size), \
                 patch.object(import_osm.ox, "graph_from_xml") as load:
                with self.assertRaises(ValueError):
                    import_osm.import_graph(self.source, self.output, nodes, size)
                load.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.output.parent.glob("osm_import_*")), [])

    def test_command_passes_source_output_and_guards(self):
        arguments = ["import_osm", "--source", str(self.source), "--path", str(self.output),
                     "--max-road-nodes", "1234", "--max-xml-mb", "20"]
        with patch("sys.argv", arguments), patch.object(import_osm, "import_graph") as run:
            import_osm.main()
        run.assert_called_once_with(self.source, self.output, 1234, 20_000_000)


if __name__ == "__main__":
    unittest.main()
