"""Run separately to download Edmonton roads and print one real road route."""

import json

from router import find_route, load_graph


def main():
    shelters = []
    for identifier, name, lon, lat in [
        ("sh_kinsmen", "Kinsmen Sports Centre", -113.516, 53.519),
        ("sh_terwillegar", "Terwillegar Rec Centre", -113.595, 53.440),
        ("sh_commonwealth", "Commonwealth Rec Centre", -113.473, 53.559),
    ]:
        shelters.append({
            "type": "Feature",
            "id": identifier,
            "properties": {"name": name, "open": True, "capacity": 100, "occupancy": 0},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })

    print("Demo shelter availability is fictional; locations are approximate.")
    print("ETA is illustrative at 30 km/h, not an actual traffic estimate.")
    print("Hazards are ignored. Routes are not safety-checked.")
    print("Loading Edmonton roads; the first run needs internet...")
    load_graph()
    result = find_route(53.520, -113.620, [], shelters)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
