"""Shared constants for the weather pipeline.

UNITS AND DIRECTION — READ BEFORE CHANGING ANYTHING:
    Wind leaves this package exactly as OpenWeather reports it with units=metric:
    speed in m/s, direction in meteorological degrees FROM (0 = from north,
    90 = from east). Converting m/s → km/h and flipping "from" into the fire's
    spread bearing happen in the engine only (backend/sim/engine/weather.py).
    Never multiply by 3.6 or add 180° here; doing it twice is the most likely
    integration bug.

Times are tz-aware UTC and serialised with a trailing Z. Never local time.
"""

from datetime import datetime, timedelta, timezone

SCHEMA = "v1"
SERIES_STEP_MIN = 60          # Contract A weather is hourly
MAX_HOLD_GAP_MIN = 180        # hold the nearest observation for at most 3 h past the data

SPEED_RANGE_MS = (0.0, 60.0)
TEMP_RANGE_C = (-50.0, 50.0)
RH_RANGE_PCT = (0.0, 100.0)

HTTP_TIMEOUT_S = 10
HTTP_RETRIES = 2
HTTP_BACKOFF_S = (0.5, 1.0)


def iso_z(dt: datetime) -> str:
    return require_utc(dt, "datetime").strftime("%Y-%m-%dT%H:%M:%SZ")


def require_utc(dt: datetime, name: str = "t0") -> datetime:
    """Reject naive or non-UTC datetimes rather than guessing a timezone."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC, got naive {dt.isoformat()}")
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC, got offset {dt.utcoffset()}")
    return dt.astimezone(timezone.utc)


def parse_utc(text: str, name: str = "t0") -> datetime:
    # Python < 3.11 fromisoformat rejects a trailing "Z".
    return require_utc(datetime.fromisoformat(text.replace("Z", "+00:00")), name)


def floor_hour(dt: datetime) -> datetime:
    return require_utc(dt).replace(minute=0, second=0, microsecond=0)


def default_t0() -> datetime:
    """Now, rounded down to the hour."""
    return floor_hour(datetime.now(timezone.utc))


def bbox_centroid(bbox) -> tuple[float, float]:
    """(lat, lon) midpoint of [min_lon, min_lat, max_lon, max_lat]."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
