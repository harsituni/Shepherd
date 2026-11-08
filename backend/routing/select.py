"""Picking and ordering the 2-4 options shown to the user (routing v3).

Order: safe first, then tight, then unsafe; unsafe options are kept, greyed, and
never dropped for being unsafe. Among `ok` routes the quicker one wins: `ok`
already means at least an hour to spare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.routing.candidates import MAX_OVERLAP, Candidate, overlap
from backend.routing.road_graph import RoadGraph

ROLE_ORDER = {"fastest": 0, "safest": 1, "alternative": 2}
THREAT_WINDOW_MIN = 120   # a shelter the fire reaches this soon after arrival ranks lower
TOP_SHELTERS = 3
MAX_OPTIONS = 4
PER_SHELTER = 2


def rank_key(c: Candidate) -> tuple:
    """Lower sorts first. Ties end on shelter id and role, so the order never jitters."""
    j = c.judgement
    tail = (c.shelter["id"], ROLE_ORDER[c.role])
    if j.status == "ok":
        threatened = (j.shelter_threat_sim_min is not None
                      and j.shelter_threat_sim_min <= j.arrival_sim_min + THREAT_WINDOW_MIN)
        return (2 if threatened else 1, c.path.total_min, 0) + tail
    group = 3 if j.status == "tight" else 4
    return (group, -j.margin_min, c.path.total_min) + tail


@dataclass
class Selection:
    options: list              # display order; the recommended option first
    best: Optional[Candidate]  # None when every option is unsafe
    no_safe_route: bool


def select(rg: Optional[RoadGraph], candidates: list, check_route_id: Optional[str] = None) -> Selection:
    ranked = sorted(candidates, key=rank_key)
    pool = []
    for c in ranked:  # plan 2.6: no two options share more than 80% of the shorter road
        if all(_overlap(rg, c, k) <= MAX_OVERLAP for k in pool):
            pool.append(c)

    # Plan 2.7: the best route of each of the top three shelters.
    picks, seen = [], set()
    for c in pool:
        if c.shelter["id"] not in seen:
            seen.add(c.shelter["id"])
            picks.append(c)
    picks = picks[:TOP_SHELTERS]
    # A safest pick around a cut road also shows the usual road, greyed.
    for p in list(picks):
        if p.role == "safest" and len(picks) < MAX_OPTIONS:
            usual = next((c for c in pool if c.shelter["id"] == p.shelter["id"] and c.role == "fastest"), None)
            if usual is not None and usual.status == "blocked" and usual not in picks:
                picks.append(usual)
    if len(picks) < 2:
        for c in pool:
            if len(picks) >= 2:
                break
            if c not in picks and _count(picks, c) < PER_SHELTER:
                picks.append(c)
    if picks and all(p.status == "blocked" for p in picks):
        picks = []
        for c in pool:  # least bad first: blocked ones sort by margin, highest first
            if len(picks) >= MAX_OPTIONS:
                break
            if _count(picks, c) < PER_SHELTER:
                picks.append(c)
    picks = sorted(picks, key=rank_key)[:MAX_OPTIONS]

    best = picks[0] if picks and picks[0].status != "blocked" else None
    if check_route_id:
        chosen = next((c for c in ranked if c.id == check_route_id), None)
        if chosen is not None:
            if chosen not in picks:
                # No near-duplicate lines, but a greyed pick never pushes out a usable one.
                picks = [p for p in picks if _overlap(rg, p, chosen) <= MAX_OVERLAP
                         or (chosen.status == "blocked" and p.status != "blocked")]
                if len(picks) >= MAX_OPTIONS:
                    picks = picks[:MAX_OPTIONS - 1]
                picks = sorted(picks + [chosen], key=rank_key)
            if chosen.status != "blocked":
                best = chosen
            else:
                best = next((p for p in picks if p.status != "blocked"), None)
    if best is not None:
        picks = [best] + [p for p in picks if p is not best]
    return Selection(picks, best, best is None)


def _count(picks, c) -> int:
    return sum(1 for p in picks if p.shelter["id"] == c.shelter["id"])


def _overlap(rg, a, b) -> float:
    if rg is None:  # straight-line estimates share no roads
        return 1.0 if a.shelter["id"] == b.shelter["id"] else 0.0
    return overlap(rg, a, b)
