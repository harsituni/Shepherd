"""Shepherd API — Step 0 + sim controls (contract v2)."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.routing.router import (
    NoRouteError, check_route, find_routes, find_routes_v3, graph_bbox, load_graph, prepare_forecast,
)
from backend.sim.controller import SimController

log = logging.getLogger(__name__)

# Routing v3 (2-4 fire-checked road routes) is the default; SHEPHERD_ROUTING=v2 brings back the old router.
ROUTING_VERSION = os.environ.get("SHEPHERD_ROUTING", "v3").strip().lower()

controller = SimController()
dropped_hazards: list[dict] = []
reports: list[dict] = []
_next_hazard_id: int = 1
_next_report_id: int = 1

# Government updates sent from the dashboard; phones poll GET /notifications.
notifications: list[dict] = []
_next_notification_id: int = 1
NOTIFICATION_SEVERITIES = {"advisory", "alert", "evacuation"}
NOTIFICATION_TARGETS = {"all", "zone"}

# Phone heartbeats upsert here. Dropped if no POST for STALE_EVACUEE_SEC (wall clock).
STALE_EVACUEE_SEC = 30
evacuees: dict[str, dict[str, Any]] = {}

# Large Edmonton reception centres (approx. coords). Capacities are demo-scale.
SHELTERS: list[dict] = [
    {
        "type": "Feature",
        "id": "sh_kinsmen",
        "properties": {
            "name": "Kinsmen Sports Centre",
            "capacity": 4000,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
    },
    {
        "type": "Feature",
        "id": "sh_terwillegar",
        "properties": {
            "name": "Terwillegar Rec Centre",
            "capacity": 3500,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.595, 53.440]},
    },
    {
        "type": "Feature",
        "id": "sh_commonwealth",
        "properties": {
            "name": "Commonwealth Rec Centre",
            "capacity": 5000,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.473, 53.559]},
    },
    {
        "type": "Feature",
        "id": "sh_clareview",
        "properties": {
            "name": "Clareview Rec Centre",
            "capacity": 3000,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.391, 53.601]},
    },
    {
        "type": "Feature",
        "id": "sh_millwoods",
        "properties": {
            "name": "Mill Woods Rec Centre",
            "capacity": 3000,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.413, 53.457]},
    },
    {
        "type": "Feature",
        "id": "sh_meadows",
        "properties": {
            "name": "The Meadows Rec Centre",
            "capacity": 3200,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.370, 53.473]},
    },
    {
        "type": "Feature",
        "id": "sh_jasper_place",
        "properties": {
            "name": "Jasper Place Leisure Centre",
            "capacity": 2800,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.582, 53.522]},
    },
    {
        "type": "Feature",
        "id": "sh_castle_downs",
        "properties": {
            "name": "Castle Downs Rec Centre",
            "capacity": 3000,
            "occupancy": 0,
            "open": True,
            "routing_endpoint": "reachable_road_point",
        },
        "geometry": {"type": "Point", "coordinates": [-113.520, 53.612]},
    },
]


async def _sim_loop() -> None:
    while True:
        await asyncio.sleep(2)
        controller.tick()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_graph()
    if ROUTING_VERSION == "v3":
        # The fire must cover every road routing can use, or far roads would look clear.
        controller.set_domain(graph_bbox())
    task = asyncio.create_task(_sim_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Shepherd API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class HazardDrop(BaseModel):
    kind: str
    lat: float
    lon: float
    radius_m: float


class ReportIn(BaseModel):
    kind: str
    lat: float
    lon: float
    note: Optional[str] = None


class NotificationIn(BaseModel):
    title: str
    message: str
    severity: str = "advisory"  # advisory | alert | evacuation
    target: str = "all"  # all | zone (residents inside a wildfire evacuation zone)


class SimStart(BaseModel):
    scenario: str = "wildfire"
    lat: float
    lon: float
    wind_kmh: float = 20
    wind_from_deg: float = 315
    fuel_dryness: float = 0.7
    humidity_pct: Optional[float] = None


class SimSpeed(BaseModel):
    multiplier: int = Field(..., description="1, 4, or 16")


class SimWind(BaseModel):
    wind_kmh: float
    wind_from_deg: float


class EvacueeIn(BaseModel):
    id: str
    lat: float
    lon: float
    route_id: Optional[str] = None
    route_status: Optional[str] = None
    shelter_id: Optional[str] = None


def circle_polygon(lat: float, lon: float, radius_m: float, n: int = 32) -> list[list[float]]:
    """Return a closed GeoJSON ring [lon, lat] approximating a circle."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    ring: list[list[float]] = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        ring.append([lon + dlon * math.cos(angle), lat + dlat * math.sin(angle)])
    ring.append(ring[0])
    return ring


def all_hazard_features() -> list[dict]:
    return list(controller.features()) + list(dropped_hazards)


def prune_evacuees(now: Optional[float] = None) -> None:
    """Remove evacuees with no heartbeat for STALE_EVACUEE_SEC."""
    cutoff = (now if now is not None else time.time()) - STALE_EVACUEE_SEC
    stale = [eid for eid, row in evacuees.items() if row["last_seen"] < cutoff]
    for eid in stale:
        del evacuees[eid]


def evacuee_features() -> list[dict]:
    prune_evacuees()
    features: list[dict] = []
    for eid, row in evacuees.items():
        features.append(
            {
                "type": "Feature",
                "id": eid,
                "properties": {
                    "route_id": row.get("route_id"),
                    "route_status": row.get("route_status"),
                    "shelter_id": row.get("shelter_id"),
                    "updated_sim_time": row.get("updated_sim_time"),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["lon"], row["lat"]],
                },
            }
        )
    return features


def _unsupported_flood() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": "unsupported_scenario",
            "message": "Flood deferred",
        },
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/shelters")
def get_shelters() -> dict:
    return {"type": "FeatureCollection", "features": SHELTERS}


@app.get("/hazards")
def get_hazards() -> dict:
    return {
        "type": "FeatureCollection",
        "sim_time": controller.sim_time,
        "features": all_hazard_features(),
    }


@app.post("/hazards", status_code=201)
def post_hazard(body: HazardDrop) -> dict:
    global _next_hazard_id
    feature_id = f"hz_{_next_hazard_id}"
    _next_hazard_id += 1
    feature = {
        "type": "Feature",
        "id": feature_id,
        "properties": {
            "kind": body.kind,
            "zone": "core",
            "source": "sim",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [circle_polygon(body.lat, body.lon, body.radius_m)],
        },
    }
    dropped_hazards.append(feature)
    return feature


@app.delete("/hazards")
def delete_hazards() -> dict:
    dropped_hazards.clear()
    return {"ok": True}


@app.get("/route")
def get_route(
    lat: float = Query(...),
    lon: float = Query(...),
    check_route_id: Optional[str] = Query(None),
    debug: bool = Query(False),
) -> dict:
    """Multi-option leave-by routes (v3 by default; contract v2 with SHEPHERD_ROUTING=v2)."""
    try:
        if ROUTING_VERSION == "v3":
            return find_routes_v3(
                lat,
                lon,
                controller.oracle(),
                SHELTERS,
                sim_time=controller.sim_time,
                check_route_id=check_route_id,
                debug=debug,
            )
        if check_route_id:
            return check_route(
                lat,
                lon,
                check_route_id,
                controller.arrival_min,
                SHELTERS,
                sim_time=controller.sim_time,
            )
        return find_routes(
            lat,
            lon,
            controller.arrival_min,
            SHELTERS,
            sim_time=controller.sim_time,
        )
    except NoRouteError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": "no_route", "message": str(exc)},
        )


@app.post("/reports", status_code=201)
def post_report(body: ReportIn) -> dict:
    global _next_report_id
    report_id = f"rp_{_next_report_id}"
    _next_report_id += 1
    feature = {
        "type": "Feature",
        "id": report_id,
        "properties": {
            "kind": body.kind,
            "note": body.note,
            "sim_time": controller.sim_time,
        },
        "geometry": {
            "type": "Point",
            "coordinates": [body.lon, body.lat],
        },
    }
    reports.append(feature)
    return {"id": report_id, "received": True}


@app.get("/reports")
def get_reports() -> dict:
    return {"type": "FeatureCollection", "features": reports}


@app.post("/notifications", status_code=201)
def post_notification(body: NotificationIn):
    """Dashboard "Send update": stored here and picked up by every phone's poll."""
    global _next_notification_id
    title, message = body.title.strip(), body.message.strip()
    if not title or not message:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_notification", "message": "Title and message are required."},
        )
    if body.severity not in NOTIFICATION_SEVERITIES or body.target not in NOTIFICATION_TARGETS:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_notification",
                "message": "severity must be advisory|alert|evacuation and target all|zone.",
            },
        )
    note = {
        "id": f"nt_{_next_notification_id}",
        "title": title,
        "message": message,
        "severity": body.severity,
        "target": body.target,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sim_time": controller.sim_time,
    }
    _next_notification_id += 1
    notifications.append(note)
    return note


@app.get("/notifications")
def get_notifications() -> dict:
    """Every update sent so far, newest first."""
    return {"notifications": list(reversed(notifications))}


@app.get("/forecast")
def get_forecast() -> dict:
    """Predicted fire outlines at +15…+120 min (contract v2)."""
    return controller.forecast()


@app.post("/evacuees")
def post_evacuee(body: EvacueeIn, response: Response) -> dict:
    """Phone location heartbeat. Upserts by id; 201 on first sight, 200 on update."""
    prune_evacuees()
    created = body.id not in evacuees
    evacuees[body.id] = {
        "lat": body.lat,
        "lon": body.lon,
        "route_id": body.route_id,
        "route_status": body.route_status,
        "shelter_id": body.shelter_id,
        "updated_sim_time": controller.sim_time,
        "last_seen": time.time(),
    }
    response.status_code = 201 if created else 200
    return {"id": body.id, "received": True}


@app.get("/evacuees")
def get_evacuees() -> dict:
    """Current phone positions for the dashboard map (stale after 30s)."""
    return {"type": "FeatureCollection", "features": evacuee_features()}


@app.get("/sim/state")
def get_sim_state() -> dict:
    return controller.status()


@app.post("/sim/start")
def post_sim_start(body: SimStart) -> dict:
    if body.scenario == "flood":
        return _unsupported_flood()
    try:
        state = controller.start(body.model_dump())
    except ValueError:
        return _unsupported_flood()
    _prepare_routing()
    return state


@app.post("/sim/pause")
def post_sim_pause() -> dict:
    return controller.pause()


@app.post("/sim/resume")
def post_sim_resume() -> dict:
    return controller.resume()


@app.post("/sim/reset")
def post_sim_reset() -> dict:
    return controller.reset()


@app.post("/sim/speed")
def post_sim_speed(body: SimSpeed) -> dict:
    return controller.set_speed(body.multiplier)


@app.post("/sim/wind")
def post_sim_wind(body: SimWind) -> dict:
    """Change wind; kicks off spread/forecast recompute (contract v2)."""
    state = controller.set_wind(body.wind_kmh, body.wind_from_deg)
    _prepare_routing()
    return state


def _prepare_routing() -> None:
    """v3: build the new forecast's road deadlines now, not on the next phone's /route."""
    if ROUTING_VERSION != "v3":
        return
    try:
        prepare_forecast(controller.oracle())
    except Exception:  # noqa: BLE001 - routing builds these lazily anyway
        log.exception("routing v3: could not prepare the forecast ahead of /route")
