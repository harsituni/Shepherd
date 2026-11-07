"""Manual Issue #44 smoke test. Uses saved roads and synthetic fire times."""

from math import cos, radians
import os

from shapely.geometry import box, shape

from backend.routing import router


def compare_routes(lat, lon, shelter):
    sim_time = 10
    fire_time = 35
    print("Calculating the normal road route with unknown fire predictions...", flush=True)
    normal = router.find_routes(lat, lon, lambda lat, lon: None, [shelter], sim_time)
    if normal["approximate"]:
        raise ValueError("This test requires real roads, not straight-line backup")
    print(f"Shelter: {normal['shelter_name']}", flush=True)
    print(f"Normal distance: {normal['distance_km']:.3f} km", flush=True)
    line = shape(normal["geometry"])
    if line.length == 0:
        raise ValueError("The normal route is too short for this test")

    # Put a small forecast area halfway along the normal road route.
    center = line.interpolate(0.5, normalized=True)
    dx = 75 / (111320 * cos(radians(center.y)))
    dy = 75 / 111320
    area = box(center.x - dx, center.y - dy, center.x + dx, center.y + dy)
    endpoints = [line.coords[0], line.coords[-1], (lon, lat),
                 shelter["geometry"]["coordinates"]]
    for end_lon, end_lat in endpoints:
        if router.ox.distance.great_circle(center.y, center.x, end_lat, end_lon) < 300:
            raise ValueError("The forecast area is too close to the start or shelter")

    def simulated_arrival(lat, lon):
        if center.x - dx <= lon <= center.x + dx and center.y - dy <= lat <= center.y + dy:
            return fire_time
        return None

    print("SYNTHETIC TEST TIMES: simulation clock T+10; fire arrives in the area at T+35.", flush=True)
    print("This is not a forecast from the wildfire simulation or real fire data.", flush=True)
    print(f"Area centre: longitude {center.x:.6f}, latitude {center.y:.6f}", flush=True)
    print("Required deadline: T+5 (35 - 30). Leaving at T+10 is already too late there.", flush=True)
    print("Predictions everywhere outside this area are UNKNOWN, not verified safe.", flush=True)
    if not line.intersects(area):
        raise ValueError("The test area did not intersect the normal road route")

    print("Searching for a road detour to the same shelter...", flush=True)
    try:
        result = router.find_routes(lat, lon, simulated_arrival, [shelter], sim_time)
    except router.NoRouteError as error:
        print(f"No valid detour found under the sampled forecast: {error}", flush=True)
        print("Resulting distance: unavailable. Detour found: no.", flush=True)
        print("30-minute rule enforced: normal route rejected; no route returned.", flush=True)
        return normal, None

    print(f"Resulting distance: {result['distance_km']:.3f} km", flush=True)
    # Check the whole returned line, not only the router's forecast samples.
    if result["approximate"] or not result["rerouted"] or shape(result["geometry"]).intersects(area):
        raise ValueError("FAIL: no verified road detour outside the blocked test area")
    print("Detour found: yes, using road geometry outside the blocked test area.", flush=True)
    print("30-minute rule enforced: PASS for this synthetic test area.", flush=True)
    print(f"Forecast complete: {result['forecast_complete']}", flush=True)
    print(result["warning"], flush=True)
    return normal, result


def main():
    path = router.ROUTING_DIR / "data" / "edmonton_demo_drive.graphml"
    if not path.is_file():
        raise FileNotFoundError(f"Saved Edmonton graph missing: {path}")
    os.environ["SHEPHERD_GRAPH_PATH"] = str(path)
    print("Manual simulation test, not navigation instructions or a safety guarantee.", flush=True)
    print(f"Loading existing roads only: {path}", flush=True)
    router.load_graph()
    if router._graph is None:
        raise RuntimeError("Saved roads could not load; refusing to test in backup mode")
    shelter = {
        "type": "Feature", "id": "sh_kinsmen",
        "properties": {"name": "Kinsmen Sports Centre", "open": True,
                       "capacity": 100, "occupancy": 0},
        "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
    }
    print("Start: latitude 53.520, longitude -113.620. Shelter availability is fictional.", flush=True)
    try:
        compare_routes(53.520, -113.620, shelter)
    except router.NoRouteError as error:
        print(f"TEST INCOMPLETE: no normal road route: {error}", flush=True)
        print("Normal/resulting distances unavailable; 30-minute rule not tested.", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
