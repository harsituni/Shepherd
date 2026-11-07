"""Manually compare routes on the saved Edmonton graph, without downloads."""

from math import cos, radians
import os

from shapely.geometry import LineString, shape

from backend.routing import router


def compare_routes(lat, lon, shelter):
    print("Calculating the normal route...", flush=True)
    normal = router.find_route(lat, lon, [], [shelter])
    print(f"Shelter: {normal['shelter_name']} ({normal['shelter_id']})", flush=True)
    print(f"Original distance: {normal['distance_km']:.3f} km", flush=True)
    line = shape(normal["geometry"])
    if line.length == 0:
        raise ValueError("The route is too short for a wildfire test")

    # Put a roughly 100-metre-wide fire halfway along the road route.
    center = line.interpolate(0.5, normalized=True)
    dx = 50 / (111320 * cos(radians(center.y)))
    dy = 50 / 111320
    fire = {
        "type": "Feature",
        "id": "hz_demo_fire",
        "properties": {"kind": "wildfire", "zone": "core", "source": "sim"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [center.x - dx, center.y - dy], [center.x + dx, center.y - dy],
            [center.x + dx, center.y + dy], [center.x - dx, center.y + dy],
            [center.x - dx, center.y - dy],
        ]]},
    }
    area = shape(fire["geometry"])
    coordinates = normal["geometry"]["coordinates"]
    destination = shelter["geometry"]["coordinates"]
    for x, y in [[lon, lat], destination, coordinates[0], coordinates[-1]]:
        distance = router.ox.distance.great_circle(center.y, center.x, y, x)
        if distance < 300:
            raise ValueError("The fire would be too close to the start or shelter")
    for connection in [[[lon, lat], coordinates[0]], [destination, coordinates[-1]]]:
        if LineString(connection).intersects(area):
            raise ValueError("The fire would block a connection to the road")
    blocked = router._blocked_edges(router._graph, [fire])
    if not blocked or not line.intersects(area):
        raise ValueError("The test fire did not block the normal route")
    print(f"Fire centre: longitude {center.x:.6f}, latitude {center.y:.6f}", flush=True)
    print(f"Blocked directed road segments: {len(blocked)}", flush=True)

    print("Calculating the wildfire route to the same shelter...", flush=True)
    try:
        detour = router.find_route(lat, lon, [fire], [shelter])
    except router.NoRouteError as error:
        print(f"No alternative route to this shelter: {error}", flush=True)
        print("New distance: unavailable. Rerouting: no reachable detour.", flush=True)
        return normal, None

    # Every returned road segment must stay outside the fire.
    if shape(detour["geometry"]).intersects(area):
        raise ValueError("FAILED: the wildfire route still touches a blocked area")
    if not detour["rerouted"]:
        raise ValueError("FAILED: the changed route was not marked as rerouted")
    print(f"New distance: {detour['distance_km']:.3f} km", flush=True)
    print(f"Distance change: {detour['distance_km'] - normal['distance_km']:+.3f} km", flush=True)
    print(f"Selected shelter: {detour['shelter_name']}", flush=True)
    print(f"Rerouted: {detour['rerouted']}", flush=True)
    print("PASS: the normal route crosses the fire; the wildfire route does not.", flush=True)
    return normal, detour


def main():
    path = router.ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
    if not path.is_file():
        raise FileNotFoundError(f"Saved Edmonton graph missing: {path}")
    os.environ["SHEPHERD_GRAPH_PATH"] = str(path)
    print("Simulated routing demonstration, not safety-certified.", flush=True)
    print(f"Loading saved roads only: {path}", flush=True)
    router.load_graph()
    shelter = {
        "type": "Feature", "id": "sh_kinsmen",
        "properties": {"name": "Kinsmen Sports Centre", "open": True, "capacity": 100, "occupancy": 0},
        "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
    }
    print("Start: latitude 53.520, longitude -113.620. Shelter availability is fictional.", flush=True)
    try:
        compare_routes(53.520, -113.620, shelter)
    except router.NoRouteError as error:
        print(f"No normal route exists for this test: {error}", flush=True)


if __name__ == "__main__":
    main()
