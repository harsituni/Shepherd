"""Ensemble members (wind perturbation) and per-cell percentiles.

Member 0 always uses the unperturbed forecast. Each other member scales every
wind speed by one factor from N(1, 0.15) clipped to 0.6–1.5 and rotates every
direction by one offset from N(0, 15°). The RNG seed comes from run_id, so the
same scenario always gives the same members.
"""

import hashlib
from dataclasses import dataclass

import numpy as np

WIND_FACTOR_SD = 0.15
WIND_FACTOR_CLIP = (0.6, 1.5)
WIND_DIR_SD_DEG = 15.0
# Stand-in for "never reached" while taking percentiles (NaN counts as +inf).
NOT_REACHED = 1e9


@dataclass(frozen=True)
class Member:
    weather: list
    wind_factor: float
    dir_offset_deg: float


def seed_from_run_id(run_id: str) -> int:
    return int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], "big")


def make_members(weather, n_ensemble, run_id) -> list[Member]:
    members = [Member(list(weather), 1.0, 0.0)]
    rng = np.random.default_rng(seed_from_run_id(run_id))
    for _ in range(n_ensemble - 1):
        factor = float(np.clip(rng.normal(1.0, WIND_FACTOR_SD), *WIND_FACTOR_CLIP))
        offset = float(rng.normal(0.0, WIND_DIR_SD_DEG))
        perturbed = [
            w.model_copy(update={
                "wind_speed_ms": w.wind_speed_ms * factor,
                "wind_dir_deg": (w.wind_dir_deg + offset) % 360,
            })
            for w in weather
        ]
        members.append(Member(perturbed, factor, offset))
    return members


def combine(arrivals, horizon_min):
    """(arrival_p50, arrival_p10) float32 arrays; NaN where not reached in horizon."""
    if len(arrivals) == 1:
        return arrivals[0], arrivals[0].copy()
    stack = np.nan_to_num(np.stack(arrivals).astype(np.float64), nan=NOT_REACHED)
    p50 = np.percentile(stack, 50, axis=0)
    p10 = np.percentile(stack, 10, axis=0)
    for layer in (p50, p10):
        layer[layer > horizon_min] = np.nan
    return p50.astype(np.float32), p10.astype(np.float32)
