"""Shepherd API — Step 0 backend."""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.routing.router import NoRouteError, find_route, load_graph
from backend.sim.wildfire import WildfireSim

sim: WildfireSim | None = None
sim_time: int = 0
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
    global sim_time
    while True:
        await asyncio.sleep(2)
        if sim is not None:
            sim.step(1)
            sim_time += 1


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global sim
    sim = WildfireSim(lat=53.535, lon=-113.663)
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
    sim_features = sim.features() if sim is not None else []
    return list(sim_features) + list(dropped_hazards)


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
        "sim_time": sim_time,
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
            "sim_time": sim_time,
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
