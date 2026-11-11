"""Recommendation engine: radius, candidates, merge, evaluation, bad-day logic, ranking.

All external access goes through injected `Providers` (the real ones call the
public APIs / Bedrock on the server; tests inject recorded mocks). Any provider
exception or timeout marks only that source as failed for the place.
"""
from __future__ import annotations

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

SPEED_KMH = 40.0
ROAD_FACTOR = 1.3
WIDEN_FACTOR = 1.5
TOP_N = 5
PRESELECT_N = 15
MERGE_RATIO = 0.8
MERGE_METERS = 100.0
API_TIMEOUT_S = 5.0
MIN_REVIEWS = 3

ALLOWED_TYPES = {"tourapi:12", "tourapi:14", "tourapi:28", "kakao:CT1", "kakao:AT4"}
INDOOR_RULE = {"tourapi:14": "indoor", "kakao:CT1": "indoor"}  # others are ambiguous -> LLM
SUIT_RANK = {"적합": 0, "보통": 1, "부적합": 2}
FAIL = "정보를 불러오지 못함"
UNKNOWN = "정보 없음"
FACILITY_KEYS = ("nursing_room", "stroller_rental", "parking")
BAD_GRADES = {"나쁨", "매우나쁨", "매우 나쁨"}
NO_REVIEW = "후기 정보 없음"
NO_DUST = "미세먼지 예보 없음"


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


@dataclass
class Providers:
    # tour_search/kakao_search(lat, lng, radius_km) -> raw places (region-code based collection)
    tour_search: Callable[[float, float, float], list[dict]]
    kakao_search: Callable[[float, float, float], list[dict]]
    facilities: Callable[[dict], dict]            # public-data facilities: {key: 있음/없음/정보 없음}
    reviews: Callable[[dict], list[dict]]         # NAVER blog/cafe snippets (<=10)
    weather: Callable[[float, float, str], dict]  # {forecast_source, precip_prob_max, temp_max, temp_min}
    dust: Callable[[float, float, str], dict]     # {pm10_grade, pm25_grade} or {} when no forecast
    llm_judge: Callable[[dict, int, list], dict]  # {age_suitability, summary[3], facility_mentions{}}
    llm_indoor_outdoor: Callable[[dict, list], str]


def _call(fn, *args):
    """Run an API call with the 5 s timeout; raises on failure/timeout."""
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=API_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


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
    }


def collect_candidates(prov: Providers, dep: tuple[float, float], radius: float, failed: list) -> list[dict]:
    raw: list[dict] = []
    for source, fn in (("tourapi", prov.tour_search), ("kakao", prov.kakao_search)):
        try:
            items = _call(fn, dep[0], dep[1], radius) or []
        except Exception:
            failed.append(source)
            continue
        for r in items:
            p = _norm_place(r, source, dep)
            if p and p["distance_km"] <= radius:
                raw.append(p)
    merged = merge_places(raw)
    merged.sort(key=lambda p: p["distance_km"])
    return merged[:PRESELECT_N]


def _count(fac: dict) -> int:
    return sum(1 for k in FACILITY_KEYS if fac.get(k, {}).get("status") == "있음")


def evaluate_bad_day(w: dict, d: dict) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if isinstance(w.get("precip_prob_max"), (int, float)) and w["precip_prob_max"] >= 60:
        warnings.append("강수")
    if d.get("pm10_grade") in BAD_GRADES or d.get("pm25_grade") in BAD_GRADES:
        warnings.append("미세먼지")
    if isinstance(w.get("temp_max"), (int, float)) and w["temp_max"] >= 33:
        warnings.append("폭염")
    if isinstance(w.get("temp_min"), (int, float)) and w["temp_min"] <= -5:
        warnings.append("한파")
    return bool(warnings), warnings


def evaluate_place(prov: Providers, p: dict, age: int, date_str: str) -> dict:
    failed: list[str] = []
    out = dict(p)

    def guarded(name, fn, *args):
        try:
            return _call(fn, *args)
        except Exception:
            failed.append(name)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_fac = ex.submit(guarded, "public_data", prov.facilities, p)
        f_rev = ex.submit(guarded, "naver", prov.reviews, p)
        f_w = ex.submit(guarded, "kma", prov.weather, p["lat"], p["lng"], date_str)
        f_d = ex.submit(guarded, "airkorea", prov.dust, p["lat"], p["lng"], date_str)
        fac_raw, reviews, weather, dust = f_fac.result(), f_rev.result(), f_w.result(), f_d.result()

    reviews_failed = reviews is None
    reviews = (reviews or [])[:10]
    out["review_evidence_count"] = len(reviews)
    out["review_insufficient"] = len(reviews) < MIN_REVIEWS

    judge = guarded("llm", prov.llm_judge, p, age, reviews) or {}
    suit = judge.get("age_suitability")
    out["age_suitability"] = suit if suit in SUIT_RANK else "보통"
    summary = list(judge.get("summary") or [])[:3]
    if reviews_failed or ("llm" in failed and reviews):
        out["review_summary"] = [FAIL]
    else:
        out["review_summary"] = summary if (reviews and summary) else [NO_REVIEW]

    # facilities: public data first, then NAVER mentions, else 정보 없음
    mentions = judge.get("facility_mentions") or {}
    public_failed = fac_raw is None
    fac: dict[str, dict] = {}
    for k in FACILITY_KEYS:
        val = (fac_raw or {}).get(k)
        if val in ("있음", "없음"):
            fac[k] = {"status": val, "source": "public_data"}
        elif mentions.get(k) in ("있음", "없음"):
            fac[k] = {"status": mentions[k], "source": "naver"}
        elif public_failed or reviews_failed or "llm" in failed:
            # a source needed to resolve this facility failed -> do not claim "정보 없음"
            fac[k] = {"status": FAIL, "source": None}
        else:
            fac[k] = {"status": UNKNOWN, "source": None}
    out["facilities"] = fac
    out["facility_count"] = _count(fac)

    # indoor / outdoor: category rule first, LLM only when ambiguous
    io = next((INDOOR_RULE[t] for t in p["types"] if t in INDOOR_RULE), None)
    if io is None:
        io = guarded("llm", prov.llm_indoor_outdoor, p, reviews)
        io = io if io in ("indoor", "outdoor") else "outdoor"
    out["indoor_outdoor"] = io

    out["weather"] = {"status": FAIL} if weather is None else dict(weather)
    if dust is None:
        out["dust"] = {"status": FAIL}
    elif not dust:
        out["dust"] = {"status": NO_DUST}
    else:
        out["dust"] = dict(dust)
    bad, warns = evaluate_bad_day(weather or {}, dust or {})
    out["is_bad_day"] = bad
    out["warnings"] = warns if io == "outdoor" else []
    out["failed_sources"] = sorted(set(failed))
    return out


def rank_places(places: list[dict]) -> list[dict]:
    def key(p):
        outdoor_bad = p["indoor_outdoor"] == "outdoor" and p["is_bad_day"]
        return (outdoor_bad, SUIT_RANK[p["age_suitability"]], -p["facility_count"], p["distance_km"])

    return sorted(places, key=key)


def _run(prov, dep, age, date_str, radius, failed) -> list[dict]:
    cands = collect_candidates(prov, dep, radius, failed)
    if not cands:
        return []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        evaluated = list(ex.map(lambda p: evaluate_place(prov, p, age, date_str), cands))
    kept = [p for p in evaluated if p["age_suitability"] != "부적합"]
    return rank_places(kept)[:TOP_N]


def recommend(
    prov: Providers,
    *,
    age_months: int,
    departure: dict,
    outing_date: str,
    travels_during_nap: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    say = progress or (lambda m: None)
    t0 = time.monotonic()
    dep = (departure["lat"], departure["lng"])
    hours = max_drive_hours(age_months, bool(travels_during_nap))
    radius = radius_km_for(hours)
    expanded = False
    failed: list[str] = []
    say("주변 장소를 찾고 있어요...")
    results = _run(prov, dep, age_months, outing_date, radius, failed)
    if len(results) < TOP_N:
        expanded = True
        radius = radius * WIDEN_FACTOR
        say("후보가 부족해 검색 반경을 1.5배로 넓혀 다시 찾고 있어요...")
        results = _run(prov, dep, age_months, outing_date, radius, failed)
    notice = None
    if len(results) < TOP_N:
        notice = f"조건에 맞는 장소가 {len(results)}곳뿐이에요. 찾은 장소만 보여드릴게요."
    say("날씨·편의시설·후기를 확인해 순위를 정했어요.")
    return {
        "max_drive_hours": hours,
        "radius_km": radius,
        "radius_expanded": expanded,
        "result_cards": results,
        "notice": notice,
        "failed_sources": sorted(set(failed)),
        "elapsed_s": time.monotonic() - t0,
    }


def recommendation_turn(graph: Any, thread_id: str, message: str, prov: Providers) -> dict:
    """One chat turn: ask-back via LangGraph; when inputs are complete, run the recommendation."""
    from .agent import chat_turn

    view = chat_turn(graph, thread_id, message)
    messages: list[str] = [view["reply"]] if view.get("reply") else []
    view["messages"] = messages
    if view["status"] != "ready":
        return view
    rec = recommend(
        prov,
        age_months=view["baby_age_months"],
        departure=view["departure_location"],
        outing_date=view["outing_date"],
        travels_during_nap=bool(view.get("travels_during_nap")),
        progress=messages.append,
    )
    view.update(rec)
    return view
