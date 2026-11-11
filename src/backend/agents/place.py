"""Place search: drive radius, candidate collection/merge, public facility lookup."""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import Optional

from ..constants import FACILITY_KEYS, FAIL, UNKNOWN
from ..tools import Providers, call_api, guarded

SPEED_KMH = 40.0
ROAD_FACTOR = 1.3
WIDEN_FACTOR = 1.5
PRESELECT_N = 15
MERGE_RATIO = 0.8
MERGE_METERS = 100.0

ALLOWED_TYPES = {"tourapi:12", "tourapi:14", "tourapi:28", "kakao:CT1", "kakao:AT4"}


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


def collect_candidates(prov: Providers, dep: tuple[float, float], radius: float) -> dict:
    """Candidates within `radius`, merged and nearest first (at most PRESELECT_N)."""
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
    merged.sort(key=lambda p: p["distance_km"])
    return {"candidates": merged[:PRESELECT_N], "failed_sources": failed}


def fetch_public_facilities(prov: Providers, p: dict) -> dict:
    """Public-data facility info; `public_facilities` is None when the call failed."""
    failed: list[str] = []
    raw = guarded(failed, "public_data", prov.facilities, p)
    return {"public_facilities": raw, "failed_sources": failed}


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
