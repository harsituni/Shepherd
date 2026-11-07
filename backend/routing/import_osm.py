"""Import a local BBBike .osm.gz file without downloading roads."""

import argparse
import gzip
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import osmnx as ox

from backend.routing.prepare_graph import GRAPH_PATH, check_graph
from backend.routing.router import ROUTING_DIR


DRIVING_ROADS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "residential", "unclassified", "living_street",
}
MAX_ROAD_NODES = 250_000
MAX_XML_BYTES = 100_000_000


def is_driving_road(way):
    tags = {}
    for tag in way.findall("tag"):
        tags[tag.attrib["k"]] = tag.attrib["v"]
    if tags.get("highway") not in DRIVING_ROADS or tags.get("area") == "yes":
        return False
    for name in ["access", "vehicle", "motor_vehicle", "motorcar"]:
        if tags.get(name) in ["no", "private", "agricultural", "forestry"]:
            return False
    if tags.get("service") in ["alley", "driveway", "emergency_access", "parking", "parking_aisle", "private"]:
        return False
    return True


def filter_roads(source, output):
    """Read in two passes so the full extract never sits in memory."""
    needed_nodes = set()
    road_count = 0
    with output.open("wb") as saved:
        saved.write(b'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6">\n')
        for pass_number in [1, 2]:
            print(f"Reading compressed XML, pass {pass_number} of 2...", flush=True)
            with gzip.open(source, "rb") as incoming:
                elements = ET.iterparse(incoming, events=("start", "end"))
                event, root = next(elements)
                if root.tag != "osm":
                    raise ValueError("Expected an OSM XML extract")
                for event, element in elements:
                    if event != "end" or element.tag not in ["node", "way", "relation", "bounds"]:
                        continue
                    if pass_number == 1 and element.tag == "way" and is_driving_road(element):
                        for node in element.findall("nd"):
                            needed_nodes.add(node.attrib["ref"])
                        road_count += 1
                        saved.write(ET.tostring(element, encoding="utf-8"))
                    if pass_number == 2 and element.tag == "node" and element.attrib["id"] in needed_nodes:
                        saved.write(ET.tostring(element, encoding="utf-8"))
                        needed_nodes.remove(element.attrib["id"])
                    # Release each finished map element.
                    root.clear()
                    if len(needed_nodes) > MAX_ROAD_NODES or saved.tell() > MAX_XML_BYTES:
                        raise ValueError("Filtered map exceeds the memory guard. Use a smaller extract.")
            if pass_number == 1:
                print(f"Keeping {road_count} roads and {len(needed_nodes)} road nodes.", flush=True)
                if road_count == 0:
                    raise ValueError("No driving roads found in the extract")
        if needed_nodes:
            raise ValueError("The extract is missing nodes referenced by driving roads")
        saved.write(b"</osm>\n")


def import_graph(source, path):
    if path.exists():
        raise FileExistsError(f"Graph already exists: {path}. Check it or choose another --path.")
    if not source.is_file():
        raise FileNotFoundError(f"OSM extract missing: {source}")
    if not source.name.endswith(".osm.gz"):
        raise ValueError("Choose an .osm.gz file")
    if ox.settings.all_oneway:
        raise ValueError("OSMnx all_oneway must be False to preserve normal road directions")

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix="osm_import_") as folder:
        filtered = Path(folder) / "driving.osm"
        filter_roads(source, filtered)
        print("Building the driving graph with OSMnx...", flush=True)
        graph = ox.graph_from_xml(filtered, bidirectional=False, simplify=True, retain_all=True)

    # Save before checking, so failed checks can be inspected offline.
    ox.save_graphml(graph, path)
    print(f"Saved roads: {path}", flush=True)
    try:
        check_graph(graph)
    except ValueError as error:
        raise ValueError(
            f"Graph saved to {path}, but did not pass validation: {error}. "
            "The file was kept for offline inspection."
        ) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Original .osm.gz file")
    parser.add_argument("--path", type=Path, default=GRAPH_PATH, help="New GraphML output")
    args = parser.parse_args()
    if args.source is None:
        files = list((ROUTING_DIR / "data").glob("*.osm.gz"))
        if len(files) != 1:
            parser.error("Expected one .osm.gz file in data. Choose one with --source.")
        args.source = files[0]
    print(f"Original extract (read only): {args.source}", flush=True)
    try:
        import_graph(args.source, args.path)
    except (OSError, ValueError, ET.ParseError, EOFError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
