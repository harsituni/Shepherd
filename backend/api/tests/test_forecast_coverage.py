"""Forecast coverage: every real road cell is in the fire domain, through the real API."""

import asyncio
import copy
from dataclasses import replace
import json
from urllib.parse import urlencode
from unittest.mock import patch

import numpy as np
import pytest

from backend.api import main as api
from backend.routing import router
from backend.routing.road_graph import TO_GRID
from backend.routing.safety import EdgeFire
from backend.sim.controller import SimController


@pytest.fixture(scope="module")
def roads():
    with patch.object(router, "_graph", None), patch.object(router, "_backup_mode", False):
        router.forget_road_graph()
        router.load_graph()
        assert router._graph is not None, "this test requires the shipped road graph"
        yield router._road_graph()
    router.forget_road_graph()


@pytest.mark.parametrize("lat,lon", [(53.535, -113.663), (53.395873, -113.442712), (53.61, -113.39)])
def test_every_road_cell_is_in_the_modeled_domain(roads, lat, lon):
    c = SimController(weather="dashboard", domain_bbox=router.graph_bbox())
    c.start(dict(lat=lat, lon=lon, wind_kmh=35, wind_from_deg=270))
    oracle = c.oracle()
    table = router._cell_table(roads, oracle)
    assert len(table.cell_flat) > 100_000
    assert np.all(table.cell_flat >= 0)
    assert np.all(table.cell_flat < len(oracle.in_domain))
    assert np.all(oracle.in_domain[table.cell_flat])
    assert not EdgeFire.for_oracle(roads, table, oracle).cell_unknown.any()


async def request(method, path, query=None, data=None):
    """Exercise FastAPI parsing/serialization without a server or extra dependencies."""
    sent = []
    raw = b"" if data is None else json.dumps(data).encode()
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    await api.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "scheme": "http", "method": method, "path": path, "raw_path": path.encode(),
                   "query_string": urlencode(query or {}).encode(), "root_path": "",
                   "headers": [(b"content-type", b"application/json")],
                   "client": ("127.0.0.1", 1), "server": ("test", 80)}, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))
    return status, body


def road_meeting_points(roads):
    """Explicit road-node endpoints to isolate FORECAST validity from access.

    Actual building coordinates are separately required to remain unverified.
    """
    shelters = copy.deepcopy(api.SHELTERS)
    for s in shelters:
        lon, lat = s["geometry"]["coordinates"]
        node = roads.nearest_node(lat, lon)[0]
        s["geometry"]["coordinates"] = [float(roads.node_lon[node]), float(roads.node_lat[node])]
    node = roads.nearest_node(53.395873, -113.442712)[0]
    return shelters, {"lat": float(roads.node_lat[node]), "lon": float(roads.node_lon[node])}


def test_actual_66_street_api_reproduction(roads, monkeypatch):
    c = SimController(weather="dashboard")
    monkeypatch.setattr(api, "controller", c)

    async def check():
        async with api.lifespan(api.app):
            code, _ = await request("POST", "/sim/start", data=dict(
                lat=53.535, lon=-113.663, wind_kmh=35, wind_from_deg=270))
            assert code == 200
            code, body = await request("GET", "/route", dict(lat=53.395873, lon=-113.442712))
            assert code == 200
            assert body["best_route_id"] is not None and body["no_safe_route"] is False
            assert body["route_status"] == "viable"
            assert all(o["access"]["destination"]["building_access_verified"] is False for o in body["options"])
            # The geographic forecast fix still establishes safe ROAD journeys:
            # replacing building endpoints with declared road meeting points
            # must recover viability without changing any fire/domain inputs.
            shelters, pin = road_meeting_points(roads)
            with patch.object(api, "SHELTERS", shelters):
                code, mapped = await request("GET", "/route", pin)
            assert code == 200 and mapped["best_route_id"] is not None
            assert mapped["no_safe_route"] is False and mapped["route_status"] == "viable"
            assert all(o["forecast_complete"] and o["access"]["complete"] for o in mapped["options"])
            assert all(o["status"] in ("ok", "tight") for o in mapped["options"])
            # A real already-burning origin remains blocked after the coverage fix.
            code, blocked = await request("GET", "/route", dict(lat=53.535, lon=-113.663))
            assert code == 200
            assert blocked["route_status"] == "blocked"
            assert blocked["no_safe_route"] is True
            assert blocked["best_route_id"] is None
            assert all(o["status"] == "blocked" for o in blocked["options"])
            return body

    asyncio.run(check())


def test_actual_api_rejects_incomplete_or_invalid_snapshots(roads, monkeypatch):
    """Real roads/API with deliberately corrupted or shortened actual snapshots."""
    c = SimController(weather="dashboard", domain_bbox=router.graph_bbox())
    c.start(dict(lat=53.535, lon=-113.663, wind_kmh=35, wind_from_deg=270))
    original = c.oracle()
    shelters, pin = road_meeting_points(roads)
    monkeypatch.setattr(api, "SHELTERS", shelters)
    assert router.find_routes(pin["lat"], pin["lon"], original, shelters)["route_status"] == "viable"
    # Warm the valid cache first: a replacement array with the same version
    # must not inherit its cached evidence of safety.
    router.prepare_forecast(original)
    mask = original.in_domain.copy()
    table = router._cell_table(roads, original)
    flat = table.grid.flat_of(*TO_GRID.transform(pin["lon"], pin["lat"]))
    mask[flat] = False  # residual uncovered 66 Street SW cell
    variants = [
        replace(original, covers_until_sim_min=1),
        replace(original, sim_time=original.covers_until_sim_min - 1),
        replace(original, in_domain=mask),
        replace(original, arrival=np.full_like(original.arrival, np.nan)),
        replace(original, arrival=np.full_like(original.arrival, -np.inf)),
        replace(original, covers_until_sim_min=np.nan),
    ]
    monkeypatch.setattr(api, "controller", c)

    async def check():
        for oracle in variants:
            monkeypatch.setattr(c, "oracle", lambda: oracle)
            code, body = await request("GET", "/route", pin)
            assert code == 200
            assert body["best_route_id"] is None
            assert body["no_safe_route"] is None
            assert body["route_status"] == "indeterminate"
            assert body["leave_by_sim_min"] is None
            assert "geometry" not in body
            assert body["options"]
            assert all(o["status"] == "indeterminate" for o in body["options"])
            assert all(not o["forecast_complete"] for o in body["options"])
            json.dumps(body, allow_nan=False)

    asyncio.run(check())
