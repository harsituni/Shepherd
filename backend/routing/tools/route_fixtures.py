"""Regenerate shared/fixtures/route_*.json from the real engine and Edmonton graph.

    python -m backend.routing.tools.route_fixtures

Each file is one real GET /route answer (dashboard wind, no OpenWeather call):
no fire, mixed (a blocked road beside its detour), no safe route, and
indeterminate (a forecast too short to cover the trip).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from backend.api.main import SHELTERS
from backend.routing import router
from backend.sim.controller import SimController

OUT = Path(__file__).resolve().parents[3] / "shared" / "fixtures"
FIRE = {"lat": 53.535, "lon": -113.663, "wind_kmh": 35, "wind_from_deg": 270}


def fire(minutes: int = 0) -> SimController:
    c = SimController(weather="dashboard", domain_bbox=router.graph_bbox())
    c.start(dict(FIRE))
    for _ in range(minutes):
        c.tick()
    return c


def main() -> None:
    router.load_graph()
    short = fire().oracle()
    cases = {
        "route_no_fire": ((53.535, -113.62), None),
        "route_mixed": ((53.535, -113.70), fire().oracle()),
        "route_no_safe_route": ((FIRE["lat"], FIRE["lon"]), fire(60).oracle()),
        "route_indeterminate": ((53.535, -113.62),
                                   dataclasses.replace(short, covers_until_sim_min=short.sim_time + 20.0)),
    }
    for name, ((lat, lon), oracle) in cases.items():
        body = router.find_routes(lat, lon, oracle, SHELTERS)
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n")
        print(f"{name}: {body['route_status']}, {[(o['id'], o['status']) for o in body['options']]}")


if __name__ == "__main__":
    main()
