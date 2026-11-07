"""Shepherd API — Step 0 + sim controls (contract v2)."""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.routing.router import NoRouteError, find_route, load_graph
from backend.sim.controller import SimController

controller = SimController()
dropped_hazards: list[dict] = []
reports: list[dict] = []
_next_hazard_id: int = 1
_next_report_id: int = 1

SHELTERS: list[dict] = [
    {
        "type": "Feature",
        "id": "sh_kinsmen",
        "properties": {
            "name": "Kinsmen Sports Centre",
            "capacity": 2000,
            "occupancy": 0,
            "open": True,
        },
        "geometry": {"type": "Point", "coordinates": [-113.516, 53.519]},
    },
    {
        "type": "Feature",
        "id": "sh_terwillegar",
        "properties": {
            "name": "Terwillegar Rec Centre",
            "capacity": 2500,
            "occupancy": 0,
            "open": True,
        },
        "geometry": {"type": "Point", "coordinates": [-113.595, 53.440]},
    },
    {
        "type": "Feature",
        "id": "sh_commonwealth",
        "properties": {
            "name": "Commonwealth Rec Centre",
            "capacity": 1500,
            "occupancy": 0,
            "open": True,
        },
        "geometry": {"type": "Point", "coordinates": [-113.473, 53.559]},
    },
]


async def _sim_loop() -> None:
    while True:
        await asyncio.sleep(2)
        controller.tick()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_graph()
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
) -> dict:
    try:
        return find_route(lat, lon, all_hazard_features(), SHELTERS)
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


@app.get("/sim/state")
def get_sim_state() -> dict:
    return controller.status()


@app.post("/sim/start")
def post_sim_start(body: SimStart) -> dict:
    if body.scenario == "flood":
        return _unsupported_flood()
    try:
        return controller.start(body.model_dump())
    except ValueError:
        return _unsupported_flood()


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
    return controller.set_wind(body.wind_kmh, body.wind_from_deg)
