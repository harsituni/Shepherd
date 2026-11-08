"""Raw-response cache, so the demo never depends on the network.

Each file is an envelope around one raw API response:
    weather_cache/{provider}_{endpoint}_{lat}_{lon}_{fetched_at}.json
    {"provider", "endpoint", "url" (no API key), "fetched_at", "lat", "lon", "response"}
A forecast fetch and its "current" anchor share fetched_at, so one can find the other.
"""

import json
import math
from datetime import datetime
from pathlib import Path

from backend.sim.weatherpipe.conventions import iso_z


def _stamp(fetched_at: datetime) -> str:
    return fetched_at.strftime("%Y%m%dT%H%M%SZ")


def cache_path(cache_dir, provider, endpoint, lat, lon, fetched_at: datetime) -> Path:
    return Path(cache_dir) / f"{provider}_{endpoint}_{lat:.4f}_{lon:.4f}_{_stamp(fetched_at)}.json"


def save_raw(cache_dir, provider, endpoint, lat, lon, fetched_at, url, response, secret=None) -> Path:
    path = cache_path(cache_dir, provider, endpoint, lat, lon, fetched_at)
    text = json.dumps({
        "provider": provider,
        "endpoint": endpoint,
        "url": url,
        "fetched_at": iso_z(fetched_at),
        "lat": lat,
        "lon": lon,
        "response": response,
    }, indent=2)
    if secret and secret in text:
        raise ValueError("refusing to write the API key to the weather cache")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    return path


def load_raw(path) -> dict:
    envelope = json.loads(Path(path).read_text())
    for key in ("provider", "endpoint", "fetched_at", "lat", "lon", "response"):
        if key not in envelope:
            raise ValueError(f"{path}: not a weather cache file (missing {key!r})")
    return envelope


def latest_forecast(cache_dir, lat, lon, endpoints) -> Path:
    """Newest cached forecast file for (lat, lon), across the given endpoints."""
    found = [
        p
        for endpoint in endpoints
        for p in Path(cache_dir).glob(f"*_{endpoint}_{lat:.4f}_{lon:.4f}_*.json")
    ]
    if not found:
        raise FileNotFoundError(f"no cached forecast for {lat:.4f}, {lon:.4f} in {cache_dir}")
    return max(found, key=lambda p: p.stem.rsplit("_", 1)[1])


def latest_forecast_near(cache_dir, lat, lon, endpoints, max_km) -> Path:
    """Newest cached forecast fetched within max_km of (lat, lon), across the given endpoints.

    A single-point forecast a few km away is as good as one at the exact point.
    """
    found = []
    for endpoint in endpoints:
        for p in Path(cache_dir).glob(f"*_{endpoint}_*.json"):
            try:
                _, _, p_lat, p_lon, stamp = p.stem.split("_")
                far = _distance_km(lat, lon, float(p_lat), float(p_lon)) > max_km
            except ValueError:
                continue
            if not far:
                found.append((stamp, p))
    if not found:
        raise FileNotFoundError(f"no cached forecast within {max_km} km of {lat:.4f}, {lon:.4f} in {cache_dir}")
    return max(found)[1]


def _distance_km(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371 * math.hypot(dlat, dlon)


def sibling_path(path, endpoint) -> Path:
    """The cache file for another endpoint from the same fetch."""
    path = Path(path)
    provider, old_endpoint, rest = path.name.split("_", 2)
    return path.with_name(f"{provider}_{endpoint}_{rest}")
