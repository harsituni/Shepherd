"""Run separately to print a saved-road route or a clearly marked backup."""

import json

from backend.routing.router import find_route, load_graph


def main():
    shelters = []
    for identifier, name, lon, lat, capacity in [
        ("sh_kinsmen", "Kinsmen Sports Centre", -113.516, 53.519, 4000),
        ("sh_terwillegar", "Terwillegar Rec Centre", -113.595, 53.440, 3500),
        ("sh_commonwealth", "Commonwealth Rec Centre", -113.473, 53.559, 5000),
        ("sh_clareview", "Clareview Rec Centre", -113.391, 53.601, 3000),
        ("sh_millwoods", "Mill Woods Rec Centre", -113.413, 53.457, 3000),
        ("sh_meadows", "The Meadows Rec Centre", -113.370, 53.473, 3200),
        ("sh_jasper_place", "Jasper Place Leisure Centre", -113.582, 53.522, 2800),
    ]:
        shelters.append({
            "type": "Feature",
            "id": identifier,
            "properties": {"name": name, "open": True, "capacity": capacity, "occupancy": 0},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })

    print("Demo shelter availability is fictional; locations are approximate.")
    print("ETA is illustrative at 30 km/h, not an actual traffic estimate.")
    print("This example has no hazards. Results are not navigation instructions.")
    print("Loading saved Edmonton roads; no downloads...")
    load_graph()
    result = find_route(53.520, -113.620, [], shelters)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
