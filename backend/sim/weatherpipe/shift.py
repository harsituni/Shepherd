"""Scripted forecast update for the demo: a wind shift ramped in over time."""

import copy


def apply_wind_shift(weather: list[dict], start_min: int, ramp_min: int,
                     rotate_deg: float, speed_factor: float) -> list[dict]:
    """Return a NEW weather list: entries before start_min unchanged; between start_min and
    start_min+ramp_min, rotation and speed factor ramp linearly from 0/1 to full; after that, full shift.
    Rotation is applied to the from-direction and wrapped to [0, 360)."""
    shifted = []
    for entry in weather:
        new = copy.deepcopy(entry)
        t = entry["t_min"]
        if t > start_min:
            frac = 1.0 if ramp_min <= 0 else min((t - start_min) / ramp_min, 1.0)
            new["wind_dir_deg"] = round(entry["wind_dir_deg"] + rotate_deg * frac) % 360
            new["wind_speed_ms"] = round(entry["wind_speed_ms"] * (1 + (speed_factor - 1) * frac), 1)
        shifted.append(new)
    return shifted
