"""Place search sub-graph: drive radius -> candidate collection/merge -> public
facility lookup per candidate (fanned out with Send) -> attach.

`collect` searches by radius (TourAPI + Kakao), or - in keyword mode - by the
preference keywords only, returning places not already known.

    START -> radius -> collect -+-> facilities (x N, parallel) -> attach -> END
                                +-> attach (no candidates)
"""
from __future__ import annotations

import math
import operator
import re
from difflib import SequenceMatcher
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..constants import FACILITY_KEYS, FAIL, UNKNOWN
from ..tools import Providers, call_api, guarded

SPEED_KMH = 40.0
ROAD_FACTOR = 1.3
WIDEN_FACTOR = 1.5
PRESELECT_N = 15
KEYWORD_N = 10
MAX_KEYWORDS = 3
MERGE_RATIO = 0.8
MERGE_METERS = 100.0

ALLOWED_TYPES = {"tourapi:12", "tourapi:14", "tourapi:28", "kakao:CT1", "kakao:AT4", "kakao:PARK", "kakao:KIDS"}


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


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def place_key(p: dict) -> str:
    """Stable id of a candidate across turns (its source ids)."""
    return "|".join(f"{k}:{v}" for k, v in sorted(p["ids"].items()))


def _norm(name: str) -> str:
    return re.sub(r"[\s()（）]", "", name or "")


def is_same_place(a: dict, b: dict) -> bool:
    if SequenceMatcher(None, _norm(a["name"]), _norm(b["name"])).ratio() < MERGE_RATIO:
        return False
    return haversine_km(a["lat"], a["lng"], b["lat"], b["lng"]) * 1000 <= MERGE_METERS


def merge_places(places: list[dict]) -> list[dict]:
    """Merge TourAPI/Kakao duplicates; a merged place keeps both ids and sources."""
    out: list[dict] = []
    for p in places:
        for m in out:
            if is_same_place(m, p):
                m["place_source"] = sorted(set(m["place_source"]) | set(p["place_source"]))
                m["ids"].update(p["ids"])
                m["types"] = sorted(set(m["types"]) | set(p["types"]))
                for k, v in p.items():
                    m.setdefault(k, v)
                break
        else:
            q = dict(p)
            q["ids"] = dict(p["ids"])
            q["types"] = list(p["types"])
            out.append(q)
    return out


def _norm_place(raw: dict, source: str, dep: tuple[float, float]) -> Optional[dict]:
    ptype = raw.get("type")
    if ptype not in ALLOWED_TYPES:
        return None
    lat, lng = raw.get("lat"), raw.get("lng")
    if lat is None or lng is None:
        return None
    return {
        "name": raw["name"], "lat": float(lat), "lng": float(lng),
        "address": raw.get("address", ""), "description": raw.get("description", ""),
        "place_source": [source], "ids": {source: raw.get("id")}, "types": [ptype],
        "distance_km": haversine_km(dep[0], dep[1], float(lat), float(lng)),
        # kept for preselection: TourAPI cat3 code or Kakao category_name, and image presence
        "category": raw.get("category") or (raw.get("description", "") if source == "kakao" else ""),
        "has_image": bool(raw.get("image")),
    }


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
    return {"candidates": preselect(merged, radius), "failed_sources": failed}


# ---------------------------------------------------------------- preselection

BAND_EDGES_KM = (0.0, 5.0, 20.0)
# kind tiers (1 = best outing destination for a baby); first match wins, small parks first
SMALL_PARK_WORDS = ("근린공원", "소공원", "어린이공원", "쌈지공원")
TIER1_WORDS = ("테마파크", "테마공원", "동물원", "아쿠아리움", "수목원", "식물원", "자연생태", "과학관",
               "키즈카페", "워터파크", "희귀동")
TIER1_NAME_WORDS = ("어린이", "키즈", "유아")
TIER2_WORDS = ("박물관", "공원", "체험", "호수", "휴양림", "민속마을", "고궁", "생태", "관광농원", "도예촌",
               "해수욕장", "썰매장")
# TourAPI cat3 codes -> names used by the tiers above (see data/tourapi_categories.json)
TOUR_CAT3_NAMES = {
    "A01010500": "자연생태관광지", "A01010600": "자연휴양림", "A01010700": "수목원", "A01011200": "해수욕장",
    "A01011700": "호수", "A01020100": "희귀동.식물", "A02010100": "고궁", "A02010600": "민속마을",
    "A02020600": "테마공원", "A02020700": "공원", "A02030100": "농.산.어촌 체험", "A02030200": "전통체험",
    "A02030400": "이색체험", "A02060100": "박물관", "A02060300": "전시관", "A02060500": "미술관/화랑",
    "A02060900": "도서관", "A03021400": "썰매장",
}


def kind_tier(p: dict) -> int:
    """1 = theme park, zoo, arboretum, science museum, kids places, ...;
    2 = museum, park, hands-on experience, lake, ...; 3 = library, gallery, small park, other."""
    name = p.get("name", "")
    cat = p.get("category", "")
    cat = TOUR_CAT3_NAMES.get(cat, cat)
    text = f"{name} {cat}"
    if any(w in text for w in SMALL_PARK_WORDS):
        return 3
    if any(w in cat or w in name for w in TIER1_WORDS) or any(w in name for w in TIER1_NAME_WORDS)             or "kakao:KIDS" in p.get("types", []):
        return 1
    if any(w in text for w in TIER2_WORDS):
        return 2
    return 3


def preselect(places: list[dict], radius: float, n: int = PRESELECT_N) -> list[dict]:
    """Pick `n` candidates spread over distance bands (0-5 km, 5-20 km, 20 km-radius):
    an equal share per band, chosen by kind tier, then image presence, then distance;
    slots a band cannot fill go to the best of the rest."""
    def key(p):
        return (kind_tier(p), not p.get("has_image"), p["distance_km"])

    edges = [e for e in BAND_EDGES_KM if e < radius] + [radius]
    bands = [sorted((p for p in places if lo <= p["distance_km"] < hi or (hi == radius and p["distance_km"] == hi)),
                    key=key) for lo, hi in zip(edges, edges[1:])]
    share = n // len(bands) if bands else n
    picked = [p for b in bands for p in b[:share]]
    rest = sorted((p for b in bands for p in b[share:]), key=key)
    picked += rest[:max(0, n - len(picked))]
    return sorted(picked, key=lambda p: p["distance_km"])


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
