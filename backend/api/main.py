"""Shepherd API: the endpoints in shared/contract.md, with state held in memory."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.routing.router import (
    NoRouteError, find_routes, fire_closed_road_features, graph_bbox, load_graph, prepare_forecast,
)
from backend.routing.evac_demand import project_evac_demand
from backend.routing.traffic import engine as traffic_engine
from backend.sim.controller import SimController

log = logging.getLogger(__name__)

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

# Priority residents: phones whose owner registered a disability ID, keyed by the
# evacuee id. Only the ID type and its last 4 characters are kept, never the full
# number. Survives missed heartbeats; the dot shows while the phone is sharing.
priority_residents: dict[str, dict[str, Any]] = {}
PRIORITY_ID_TYPES = {"dats", "parking_placard", "aish", "adap", "pdd", "cnib", "other"}
PRIORITY_NEEDS = {"mobility", "no_vehicle", "vision", "hearing", "medical", "cognitive", "other"}

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
        # Phones count as cars; rebalance simulated crowd every few sim-minutes.
        traffic_engine.sync_phones(evacuees)
        traffic_engine.on_sim_tick(controller.sim_time)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_graph()
    # The fire must cover every road routing can use, or far roads would look clear.
    controller.set_domain(graph_bbox())
    traffic_engine.set_shelters(lambda: SHELTERS)
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
    # Tornado peak Enhanced Fujita category (0–5). Ignored for wildfire.
    ef_rating: Optional[int] = None


class SimSpeed(BaseModel):
    multiplier: int = Field(..., description="1, 4, or 16")


class SimWind(BaseModel):
    wind_kmh: float
    wind_from_deg: float


class TrafficConfig(BaseModel):
    """POST /traffic/config body; every field is optional."""
    enabled: Optional[bool] = None
    anti_gridlock: Optional[bool] = None
    simulated_count: Optional[int] = None


class PriorityIn(BaseModel):
    id: str  # the phone's evacuee id (ev_...)
    id_type: str  # one of PRIORITY_ID_TYPES
    id_last4: str  # last 4 characters of the ID number only
    needs: list[str] = Field(default_factory=list)  # PRIORITY_NEEDS
    note: Optional[str] = None


class EvacueeIn(BaseModel):
    id: str
    lat: float
    lon: float
    route_id: Optional[str] = None
    route_status: Optional[str] = None
    shelter_id: Optional[str] = None
    # Optional LineString coords [[lon, lat], ...] so the dashboard can draw the
    # phone's live route (and flash when it mid-trip reroutes). Additive.
    route_coords: Optional[list[list[float]]] = None


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


def priority_properties(eid: str) -> dict:
    """What responders see for a priority resident (no full ID number)."""
    row = priority_residents.get(eid)
    if not row:
        return {"priority": False}
    return {
        "priority": True,
        "priority_id_type": row["id_type"],
        "priority_needs": row["needs"],
        "priority_note": row["note"],
    }


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
                    "reroutes": int(row.get("reroutes") or 0),
                    "route_coords": row.get("route_coords"),
                    **priority_properties(eid),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["lon"], row["lat"]],
                },
            }
        )
    return features


def _unsupported_scenario() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": "unsupported_scenario",
            "message": "Scenario must be wildfire or tornado (beta)",
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
    """2-4 fire-checked road routes from the pin to open shelters."""
    try:
        forecast = controller.forecast()
        return find_routes(
            lat,
            lon,
            controller.oracle(),
            SHELTERS,
            sim_time=controller.sim_time,
            check_route_id=check_route_id,
            debug=debug,
            hazards={"type": "FeatureCollection", "features": controller.features()},
            forecast_outlines=forecast.get("outlines") or [],
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
    """Predicted hazard outlines at +15…+120 min."""
    return controller.forecast()


@app.get("/roads/closed")
def get_closed_roads() -> dict:
    """OSM edges already past the fire close deadline (arrival_min − 30).

    Dashboard paints these red so judges see corridors shut as the fire grows.
    `count` is the full closed set; `features` is capped for the map payload.
    """
    return fire_closed_road_features(controller.oracle(), controller.sim_time)


@app.get("/traffic/projection")
def get_traffic_projection(
    lat: float = Query(...),
    lon: float = Query(...),
    scenario: str = Query("wildfire"),
    wind_kmh: float = Query(20.0),
    when: Optional[str] = Query(None),
) -> dict:
    """Estimate evacuating people/cars from pin location + local day/time."""
    return project_evac_demand(
        lat, lon, scenario=scenario, wind_kmh=wind_kmh, when=when,
    )


@app.get("/traffic")
def get_traffic() -> dict:
    """Congested roads + metrics."""
    traffic_engine.sync_phones(evacuees)
    body = traffic_engine.payload()
    body["sim_time"] = controller.sim_time
    return body


@app.get("/traffic/state")
def get_traffic_state() -> dict:
    traffic_engine.sync_phones(evacuees)
    body = traffic_engine.status()
    body["sim_time"] = controller.sim_time
    return body


@app.post("/traffic/config")
def post_traffic_config(body: TrafficConfig) -> dict:
    traffic_engine.sync_phones(evacuees)
    state = traffic_engine.configure(
        enabled=body.enabled,
        anti_gridlock=body.anti_gridlock,
        simulated_count=body.simulated_count,
    )
    state["sim_time"] = controller.sim_time
    return state


@app.post("/traffic/compare")
def post_traffic_compare() -> dict:
    """Naive pile-up vs anti-gridlock clearance times."""
    traffic_engine.sync_phones(evacuees)
    result = traffic_engine.compare(sim_time=controller.sim_time)
    result["sim_time"] = controller.sim_time
    return result


@app.post("/traffic/rebalance")
def post_traffic_rebalance() -> dict:
    traffic_engine.sync_phones(evacuees)
    state = traffic_engine.rebalance_now(sim_time=controller.sim_time)
    state["sim_time"] = controller.sim_time
    return state


@app.get("/route/traffic_hint")
def get_traffic_hint(
    lat: float = Query(...),
    lon: float = Query(...),
    route_id: Optional[str] = Query(None),
) -> dict:
    """Phone banner helper: faster route available under current traffic."""
    hint = traffic_engine.faster_route_hint(lat, lon, route_id, sim_time=controller.sim_time)
    return {"hint": hint, "sim_time": controller.sim_time}


@app.post("/evacuees")
def post_evacuee(body: EvacueeIn, response: Response) -> dict:
    """Phone location heartbeat. Upserts by id; 201 on first sight, 200 on update."""
    prune_evacuees()
    created = body.id not in evacuees
    prev = evacuees.get(body.id) or {}
    coords = body.route_coords
    if coords is not None and len(coords) >= 2:
        route_coords = [[float(p[0]), float(p[1])] for p in coords if len(p) >= 2]
    else:
        route_coords = prev.get("route_coords")
    reroutes = int(prev.get("reroutes") or 0)
    if (
        not created
        and body.route_id
        and prev.get("route_id")
        and body.route_id != prev.get("route_id")
    ):
        reroutes += 1
    evacuees[body.id] = {
        "lat": body.lat,
        "lon": body.lon,
        "route_id": body.route_id,
        "route_status": body.route_status,
        "shelter_id": body.shelter_id,
        "route_coords": route_coords,
        "reroutes": reroutes,
        "updated_sim_time": controller.sim_time,
        "last_seen": time.time(),
    }
    response.status_code = 201 if created else 200
    return {"id": body.id, "received": True}


def _invalid_priority(message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "invalid_priority", "message": message})


@app.post("/priority")
def post_priority(body: PriorityIn, response: Response):
    """Phone "Priority" sheet: mark this phone as a priority resident. Upserts by id."""
    last4 = body.id_last4.strip()
    if not body.id.startswith("ev_"):
        return _invalid_priority("id must be the phone's evacuee id (ev_...).")
    if body.id_type not in PRIORITY_ID_TYPES:
        return _invalid_priority("Unknown ID type.")
    if len(last4) != 4 or not last4.isalnum():
        return _invalid_priority("id_last4 must be the last 4 letters or digits of the ID.")
    needs = [n for n in dict.fromkeys(body.needs) if n in PRIORITY_NEEDS]
    if len(needs) != len(set(body.needs)):
        return _invalid_priority("Unknown need.")
    note = (body.note or "").strip()[:200] or None
    created = body.id not in priority_residents
    priority_residents[body.id] = {
        "id_type": body.id_type,
        "id_last4": last4.upper(),
        "needs": needs,
        "note": note,
        "sim_time": controller.sim_time,
    }
    response.status_code = 201 if created else 200
    return {"id": body.id, "priority": True}


@app.delete("/priority/{evacuee_id}")
def delete_priority(evacuee_id: str) -> dict:
    """Phone removes its own priority status."""
    priority_residents.pop(evacuee_id, None)
    return {"id": evacuee_id, "priority": False}


@app.get("/evacuees")
def get_evacuees() -> dict:
    """Current phone positions for the dashboard map (stale after 30s)."""
    return {"type": "FeatureCollection", "features": evacuee_features()}


@app.get("/sim/state")
def get_sim_state() -> dict:
    state = controller.status()
    # Additive traffic summary for the dashboard metrics card.
    state["traffic"] = traffic_engine.status()
    return state


@app.post("/sim/start")
def post_sim_start(body: SimStart) -> dict:
    try:
        state = controller.start(body.model_dump())
    except ValueError:
        return _unsupported_scenario()
    # Crowd size from location + current Edmonton day/time (projected cars).
    traffic_engine.set_cluster(body.lat, body.lon)
    demand = project_evac_demand(
        body.lat,
        body.lon,
        scenario=body.scenario,
        wind_kmh=float(body.wind_kmh or 20.0),
    )
    traffic_engine.configure(
        enabled=True,
        anti_gridlock=True,
        simulated_count=int(demand["cars"]),
    )
    _prepare_routing()
    state = controller.status()
    state["traffic"] = traffic_engine.status()
    state["evac_demand"] = demand
    return state


@app.post("/sim/pause")
def post_sim_pause() -> dict:
    return controller.pause()


@app.post("/sim/resume")
def post_sim_resume() -> dict:
    return controller.resume()


@app.post("/sim/reset")
def post_sim_reset() -> dict:
    state = controller.reset()
    # Idle map should be clean — don't leave thousands of jam colours from the
    # last drill painted before the next wildfire is placed.
    traffic_engine.configure(enabled=False)
    state["traffic"] = traffic_engine.status()
    return state


@app.post("/sim/speed")
def post_sim_speed(body: SimSpeed) -> dict:
    return controller.set_speed(body.multiplier)


@app.post("/sim/wind")
def post_sim_wind(body: SimWind) -> dict:
    """Change wind; kicks off spread/forecast recompute."""
    state = controller.set_wind(body.wind_kmh, body.wind_from_deg)
    _prepare_routing()
    return state


def _prepare_routing() -> None:
    """Build the new forecast's road deadlines now, not on the next phone's /route."""
    try:
        prepare_forecast(controller.oracle())
    except Exception:  # noqa: BLE001 - routing builds these lazily anyway
        log.exception("routing: could not prepare the forecast ahead of /route")
