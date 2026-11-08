"""Routing v3 benchmark: checks the request-path budgets and exits 1 if one is missed.

In-process (default): loads the saved Edmonton graph, starts a fire in a local sim
and times each step against its budget.

    python -m backend.routing.bench_routes

Against a running API (start it with SHEPHERD_ROUTING=v3): replays the scenario pins
at 1, 5 and 15 clients, each polling every 2 s. This starts a fire on that server
unless --no-start is given.

    python -m backend.routing.bench_routes --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np
from scipy.sparse.csgraph import dijkstra

FIRE = {"lat": 53.535, "lon": -113.663, "wind_kmh": 35, "wind_from_deg": 270}
PINS = [  # the integration scenarios' pins
    (53.535, -113.62),     # 1 no fire nearby
    (53.535, -113.70),     # 2 upwind
    (53.535, -113.64),     # 3 downwind
    (53.53, -113.585),     # 4 close downwind
    (53.535, -113.663),    # 5 inside the fire
    (53.51, -113.50),      # 7 near a shelter
    (53.3958, -113.3445),  # 9 across the city
]
POLL_SEC = 2.0

failures: list = []


def check(name: str, value: float, budget: float, unit: str = "ms") -> None:
    ok = value < budget
    print(f"  {'ok  ' if ok else 'MISS'} {name:<44} {value:9.2f} {unit}  (budget < {budget:g} {unit})")
    if not ok:
        failures.append(name)


def p95(values) -> float:
    return float(np.percentile(values, 95))


def bench_in_process(rounds: int) -> None:
    from backend.api.main import SHELTERS
    from backend.routing import router
    from backend.routing.candidates import MAX_FIXPOINT_ROUNDS
    from backend.routing.road_graph import FireGrid, build_cell_table
    from backend.routing.safety import EdgeFire
    from backend.sim.controller import SimController

    clock = time.perf_counter()
    router.load_graph()
    if router._graph is None:
        sys.exit("No saved road graph: the benchmark needs backend/routing/data.")
    rg = router._road_graph()
    print(f"Graph: {rg.n_nodes:,} nodes, {rg.n_edges:,} edges, loaded in {time.perf_counter() - clock:.2f} s")

    rng = np.random.default_rng(7)
    lo_lon, lo_lat, hi_lon, hi_lat = router.DEMO_BBOX
    lats, lons = rng.uniform(lo_lat, hi_lat, 2000), rng.uniform(lo_lon, hi_lon, 2000)
    clock = time.perf_counter()
    for lat, lon in zip(lats, lons):
        rg.nearest_node(lat, lon)
    check("snap to road, per call", (time.perf_counter() - clock) * 1000 / len(lats), 1.0)

    times = []
    for start in rng.integers(0, rg.n_nodes, 50):
        clock = time.perf_counter()
        dijkstra(rg.csr_time, directed=True, indices=int(start), return_predecessors=True)
        times.append((time.perf_counter() - clock) * 1000)
    check("one dijkstra over the city, slowest of 50", max(times), 10.0)

    c = SimController(weather="dashboard", domain_bbox=router.graph_bbox())
    clock = time.perf_counter()
    c.start(dict(FIRE))
    print(f"Fire domain {c.oracle().nrows} x {c.oracle().ncols} cells, "
          f"started in {time.perf_counter() - clock:.2f} s")
    clock = time.perf_counter()
    table = build_cell_table(rg, FireGrid.of(c.oracle()))
    check("road-to-cell table, once per grid", (time.perf_counter() - clock) * 1000, 1000.0)

    builds = []
    for deg in (270, 300, 330, 0, 30):
        c.set_wind(FIRE["wind_kmh"], deg)
        oracle = c.oracle()
        clock = time.perf_counter()
        EdgeFire.for_oracle(rg, table, oracle)
        builds.append((time.perf_counter() - clock) * 1000)
    check("EdgeFire per new forecast, slowest of 5", max(builds), 50.0)

    c.reset()
    c.start(dict(FIRE))
    router.prepare_forecast(c.oracle())
    totals, rounds_seen = [], []
    for _ in range(rounds):
        c.tick()
        for lat, lon in PINS:
            clock = time.perf_counter()
            body = router.find_routes_v3(lat, lon, c.oracle(), SHELTERS, sim_time=c.sim_time, debug=True)
            totals.append((time.perf_counter() - clock) * 1000)
            rounds_seen.append(body["timings"]["fixpoint_rounds"])
    print(f"/route with a fire: {len(totals)} requests over {rounds} sim minutes")
    check("whole route, 1 client, mean", statistics.mean(totals), 100.0)
    check("whole route, 1 client, p95", p95(totals), 150.0)
    check("safe-search rounds, most seen", max(rounds_seen), MAX_FIXPOINT_ROUNDS, "rounds")


def get(url: str):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def poll(base: str, offset: int, stop_at: float, out: list, errors: list, lock: threading.Lock) -> None:
    i = offset
    while time.monotonic() < stop_at:
        lat, lon = PINS[i % len(PINS)]
        i += 1
        started = time.perf_counter()
        try:
            get(f"{base}/route?lat={lat}&lon={lon}")
        except urllib.error.HTTPError as error:
            if error.code != 404:  # 404 is a normal answer (outside the area)
                with lock:
                    errors.append(error.code)
        except OSError as error:
            with lock:
                errors.append(str(error))
        took = time.perf_counter() - started
        with lock:
            out.append((time.monotonic(), took))
        time.sleep(max(0.0, POLL_SEC - took))


def run_level(base: str, clients: int, seconds: float):
    out, errors, lock = [], [], threading.Lock()
    stop_at = time.monotonic() + seconds
    threads = [threading.Thread(target=poll, args=(base, k, stop_at, out, errors, lock), daemon=True)
               for k in range(clients)]
    for t in threads:
        t.start()
        time.sleep(POLL_SEC / clients)  # spread the clients over the poll period
    for t in threads:
        t.join()
    return sorted(out), errors


def bench_url(base: str, levels: list, seconds: float, long_seconds: float, start: bool) -> None:
    base = base.rstrip("/")
    if start:
        request = urllib.request.Request(f"{base}/sim/start", data=json.dumps(FIRE).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(request, timeout=60).read()
        print(f"Started a fire at {FIRE['lat']}, {FIRE['lon']} on {base}")
    probe = get(f"{base}/route?lat={PINS[2][0]}&lon={PINS[2][1]}&debug=1")
    if "timings" not in probe:
        sys.exit("The server is answering routing v2. Start it with SHEPHERD_ROUTING=v3.")

    for clients in levels:
        length = long_seconds if clients == max(levels) else seconds
        print(f"{clients} client(s) polling every {POLL_SEC:g} s for {length:g} s")
        samples, errors = run_level(base, clients, length)
        took = [s[1] * 1000 for s in samples]
        print(f"  {len(took)} requests, {len(errors)} errors, median {statistics.median(took):.0f} ms, "
              f"max {max(took):.0f} ms")
        if errors:
            failures.append(f"{clients} clients: errors {errors[:3]}")
        if clients == 1:
            check("whole /route, 1 client, mean", statistics.mean(took), 100.0)
            check("whole /route, 1 client, p95", p95(took), 150.0)
        if clients >= 15:
            check(f"whole /route, {clients} clients, p95", p95(took) / 1000, 2.0, "s")
            # A growing queue shows up as later requests waiting longer than early ones.
            fifth = max(1, len(samples) // 5)
            early = statistics.median(s[1] for s in samples[:fifth])
            late = statistics.median(s[1] for s in samples[-fifth:])
            growing = late > 2 * early and late > 0.5
            print(f"  {'MISS' if growing else 'ok  '} queue not growing: median {early * 1000:.0f} ms "
                  f"in the first fifth, {late * 1000:.0f} ms in the last")
            if growing:
                failures.append(f"{clients} clients: queue growing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="base URL of a running API; omit to benchmark in-process")
    parser.add_argument("--rounds", type=int, default=20, help="in-process: sim minutes to replay")
    parser.add_argument("--levels", default="1,5,15", help="--url: concurrent clients per level")
    parser.add_argument("--seconds", type=float, default=60, help="--url: length of each level")
    parser.add_argument("--long-seconds", type=float, default=300,
                        help="--url: length of the largest level (the queue check)")
    parser.add_argument("--no-start", action="store_true", help="--url: use the fire already running")
    args = parser.parse_args()

    if args.url:
        levels = sorted(int(n) for n in args.levels.split(","))
        bench_url(args.url, levels, args.seconds, args.long_seconds, not args.no_start)
    else:
        bench_in_process(args.rounds)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        sys.exit(1)
    print("All budgets met.")


if __name__ == "__main__":
    main()
