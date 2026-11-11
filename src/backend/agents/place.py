"""Place search sub-graph: drive radius -> candidate collection/merge -> public
facility lookup per candidate (fanned out with Send) -> attach.

`collect` searches by radius (TourAPI + Kakao), or - in keyword mode - by the
preference keywords only, returning places not already known.

    START -> radius -> collect -+-> facilities (x N, parallel) -> attach -> END
                                +-> attach (no candidates)
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..core.constants import FACILITY_KEYS, FAIL, UNKNOWN
from ..tools import Providers, call_api, guarded
from .candidates import _norm_place, group_facilities, is_same_place, merge_places, preselect

SPEED_KMH = 40.0
ROAD_FACTOR = 1.3
WIDEN_FACTOR = 1.5
KEYWORD_N = 10
MAX_KEYWORDS = 3



def max_drive_hours(age_months: int, travels_during_nap: bool) -> float:
    if age_months <= 12:
        h = 1.0
    elif age_months <= 24:
        h = 1.5
    else:
        h = 2.0
    if age_months < 24 and travels_during_nap:
        h += 1.0
    return h


def radius_km_for(hours: float) -> float:
    return hours * SPEED_KMH / ROAD_FACTOR


def collect_candidates(prov: Providers, dep: tuple[float, float], radius: float) -> dict:
    """Candidates within `radius`, merged, then PRESELECT_N picked by `preselect`."""
    failed: list[str] = []
    raw: list[dict] = []
    for source, fn in (("tourapi", prov.tour_search), ("kakao", prov.kakao_search)):
        try:
            items = call_api(fn, dep[0], dep[1], radius) or []
        except Exception:
            failed.append(source)
            continue
        for r in items:
            p = _norm_place(r, source, dep)
            if p and p["distance_km"] <= radius:
                raw.append(p)
    merged = merge_places(raw)
    return {"candidates": preselect(group_facilities(merged), radius), "failed_sources": failed}


def collect_by_keywords(prov: Providers, dep: tuple[float, float], radius: float,
                        keywords: list[str], exclude: list[dict]) -> dict:
    """Extra candidates found by preference keywords within `radius`, excluding places
    already in `exclude` (at most KEYWORD_N)."""
    failed: list[str] = []
    if prov.keyword_search is None:
        return {"candidates": [], "failed_sources": failed}
    raw: list[dict] = []
    for kw in keywords[:MAX_KEYWORDS]:
        try:
            items = call_api(prov.keyword_search, kw, dep[0], dep[1], radius) or []
        except Exception:
            failed.append("keyword_search")
            continue
        for r in items:
            p = _norm_place(r, r.get("source", "tourapi"), dep)
            if p and p["distance_km"] <= radius:
                raw.append(p)
    fresh = [p for p in merge_places(raw) if not any(is_same_place(p, e) for e in exclude)]
    fresh.sort(key=lambda p: p["distance_km"])
    return {"candidates": fresh[:KEYWORD_N], "failed_sources": sorted(set(failed))}


def resolve_facilities(public: Optional[dict], mentions: dict, *, mentions_failed: bool) -> dict:
    """Public data first, then NAVER review mentions, else 정보 없음.

    When a source needed to resolve a facility failed, show 정보를 불러오지 못함
    instead of claiming 정보 없음.
    """
    public_failed = public is None
    fac: dict[str, dict] = {}
    for k in FACILITY_KEYS:
        val = (public or {}).get(k)
        if val in ("있음", "없음"):
            fac[k] = {"status": val, "source": "public_data"}
        elif mentions.get(k) in ("있음", "없음"):
            fac[k] = {"status": mentions[k], "source": "naver"}
        elif public_failed or mentions_failed:
            fac[k] = {"status": FAIL, "source": None}
        else:
            fac[k] = {"status": UNKNOWN, "source": None}
    return fac


# ---------------------------------------------------------------- sub-graph

class PlaceState(TypedDict, total=False):
    # input
    departure: dict                 # {"lat", "lng"}
    age_months: int
    travels_during_nap: bool
    radius_scale: float             # 1.0, or WIDEN_FACTOR when the supervisor widens the search
    keywords: list[str]             # keyword mode: only search these preference keywords
    exclude: list[dict]             # keyword mode: places already known
    # output
    max_drive_hours: float
    radius_km: float
    candidates: list[dict]          # each with "public_facilities" (None = failed) and "public_failed_sources"
    failed_sources: Annotated[list[str], operator.add]   # candidate-collection failures
    # internal (fan-out results)
    facility_results: Annotated[list[tuple], operator.add]


def build_graph(prov: Providers):
    def radius(state: PlaceState) -> dict:
        hours = max_drive_hours(state["age_months"], bool(state.get("travels_during_nap")))
        return {"max_drive_hours": hours, "radius_km": radius_km_for(hours) * state.get("radius_scale", 1.0)}

    def collect(state: PlaceState) -> dict:
        dep = (state["departure"]["lat"], state["departure"]["lng"])
        if state.get("keywords"):
            return collect_by_keywords(prov, dep, state["radius_km"], state["keywords"],
                                       state.get("exclude") or [])
        return collect_candidates(prov, dep, state["radius_km"])

    def fan_out(state: PlaceState):
        cands = state.get("candidates") or []
        if not cands:
            return "attach"
        return [Send("facilities", {"index": i, "place": p}) for i, p in enumerate(cands)]

    def facilities(item: dict) -> dict:
        failed: list[str] = []
        raw = guarded(failed, "public_data", prov.facilities, item["place"])
        return {"facility_results": [(item["index"], raw, failed)]}

    def attach(state: PlaceState) -> dict:
        by_index = {i: (raw, failed) for i, raw, failed in state.get("facility_results") or []}
        cands = []
        for i, p in enumerate(state.get("candidates") or []):
            raw, failed = by_index.get(i, (None, ["public_data"]))
            extra = {}
            if isinstance(raw, dict) and raw.get("overview"):
                extra["description"] = raw["overview"]      # TourAPI overview beats a category label
            cands.append({**p, **extra, "public_facilities": raw, "public_failed_sources": failed})
        return {"candidates": cands}

    g = StateGraph(PlaceState)
    g.add_node("radius", radius)
    g.add_node("collect", collect)
    g.add_node("facilities", facilities)
    g.add_node("attach", attach)
    g.add_edge(START, "radius")
    g.add_edge("radius", "collect")
    g.add_conditional_edges("collect", fan_out, ["facilities", "attach"])
    g.add_edge("facilities", "attach")
    g.add_edge("attach", END)
    return g.compile()


def run(graph: Any, *, departure: dict, age_months: int, travels_during_nap: bool,
        radius_scale: float = 1.0, keywords: Optional[list[str]] = None,
        exclude: Optional[list[dict]] = None) -> dict:
    """Radius search, or (with `keywords`) keyword search for extra candidates."""
    s = graph.invoke({
        "departure": departure, "age_months": age_months,
        "travels_during_nap": bool(travels_during_nap), "radius_scale": radius_scale,
        "keywords": list(keywords or []), "exclude": list(exclude or []),
    })
    return {
        "max_drive_hours": s["max_drive_hours"],
        "radius_km": s["radius_km"],
        "candidates": s.get("candidates") or [],
        "failed_sources": list(s.get("failed_sources") or []),
    }
