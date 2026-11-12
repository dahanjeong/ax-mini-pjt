"""Candidate handling for the place search: normalization of raw TourAPI / Kakao places,
merging duplicates, grouping one facility's many entries, the family-outing grade and
kind, and the preselection of PRESELECT_N candidates over distance bands."""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Optional

from ..core.geo import haversine_km

PRESELECT_N = 15
MERGE_RATIO = 0.8
MERGE_METERS = 100.0
ALLOWED_TYPES = {"tourapi:12", "tourapi:14", "tourapi:28", "kakao:CT1", "kakao:AT4", "kakao:PARK", "kakao:KIDS"}


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


# ---------------------------------------------------------------- one facility, many entries

SAME_FACILITY_KM = 1.0
MIN_SHARED_PREFIX = 4
_BRACKETED = re.compile(r"\(.*?\)|\[.*?\]")


def _compact(name: str) -> str:
    return re.sub(r"\s+", "", _BRACKETED.sub(" ", name or ""))


def _first_word(name: str) -> str:
    words = _BRACKETED.sub(" ", name or "").split()
    return words[0] if words else ""


def same_facility(a: dict, b: dict) -> bool:
    """'서울대공원' / '서울대공원 제1아프리카관': the shared name prefix is a whole first word
    of one of them (at least MIN_SHARED_PREFIX characters) and they are within 1 km."""
    ca, cb = _compact(a["name"]), _compact(b["name"])
    n = 0
    while n < min(len(ca), len(cb)) and ca[n] == cb[n]:
        n += 1
    shared = ca[:n]
    if len(shared) < MIN_SHARED_PREFIX or shared not in (_first_word(a["name"]), _first_word(b["name"])):
        return False
    return haversine_km(a["lat"], a["lng"], b["lat"], b["lng"]) <= SAME_FACILITY_KM


def group_facilities(places: list[dict]) -> list[dict]:
    """Collapse entries of one facility (Kakao lists zoo sections, rides, ... separately)
    into one candidate shown under the shared name ("서울대공원"); the entries' own names go
    to `includes`. The representative (whose ids, facilities and location are used): the plain
    facility entry ("서울대공원") if there is one, else the part with the best outing grade
    once the shared name is removed ("어린이동물원" over "산림욕장"), then the shorter
    name, then a TourAPI-listed one."""
    groups: list[list[dict]] = []
    for p in sorted(places, key=lambda p: p["distance_km"]):
        for g in groups:
            if any(same_facility(m, p) for m in g):
                g.append(p)
                break
        else:
            groups.append([p])
    out = []
    for g in groups:
        rep = _representative(g)
        name = _shared_name(g) or rep["name"]
        out.append({**rep, "name": name, "includes": [m["name"] for m in g if m["name"] != name]})
    return out


def _shared_name(members: list[dict]) -> Optional[str]:
    """'서울대공원' for '서울대공원 맹수사' + '서울대공원 산림욕장': the shared name when it is the
    whole first word of a member (else None)."""
    if len(members) < 2:
        return None
    shared = os.path.commonprefix([_compact(m["name"]) for m in members])
    for m in members:
        if _first_word(m["name"]) == shared:
            return shared
    return None


def _representative(members: list[dict]) -> dict:
    if len(members) == 1:
        return members[0]
    names = [_compact(m["name"]) for m in members]
    shared = os.path.commonprefix(names)
    for m, n in zip(members, names):
        if n == shared:
            return m

    def key(i):
        m = members[i]
        part = {**m, "name": names[i][len(shared):]}
        return (outing_grade(part), len(names[i]), "tourapi" not in m["place_source"], m["distance_km"])

    return members[min(range(len(members)), key=key)]


# ---------------------------------------------------------------- preselection

BAND_EDGES_KM = (0.0, 5.0, 20.0)
# Family-outing grade (A = destination, B = half-day, C = everyday) and a kind label used
# to keep the final picks varied. Checked on the name and the category (Kakao
# category_name, or the TourAPI cat3 name).
SMALL_PARK_WORDS = ("근린공원", "소공원", "어린이공원", "쌈지공원")
GRADE_A_WORDS = ("동물원", "테마파크", "테마공원", "아쿠아리움", "수목원", "식물원", "자연생태", "생태공원",
                 "습지", "과학관", "관광농원", "농.산.어촌", "체험농장", "워터파크", "대공원", "희귀동")
GRADE_C_WORDS = ("키즈카페", "방방", "실내놀이터", "트램펄린", "도서관", "갤러리", "화랑", "미술관", "전시관")
GRADE_B_WORDS = ("박물관", "체험", "호수", "민속마을", "고궁", "공원", "휴양림", "해수욕장", "썰매장", "도예촌",
                 "생태")
KIND_WORDS = (   # first match wins
    ("zoo", ("동물원", "아쿠아리움", "희귀동")),
    ("kids", ("키즈카페", "방방", "실내놀이터", "트램펄린")),
    ("themepark", ("테마파크", "테마공원", "워터파크", "대공원", "썰매장")),
    ("museum", ("과학관", "박물관", "미술관", "전시관", "갤러리", "화랑")),
    ("experience", ("체험", "관광농원", "농.산.어촌", "도예촌", "민속마을")),
    ("nature", ("수목원", "식물원", "생태", "습지", "호수", "휴양림", "해수욕장")),
    ("park", ("공원",)),
    ("library", ("도서관",)),
    ("heritage", ("고궁",)),
)

# TourAPI cat3 codes -> names used by the tiers above (see data/tourapi_categories.json)
TOUR_CAT3_NAMES = {
    "A01010500": "자연생태관광지", "A01010600": "자연휴양림", "A01010700": "수목원", "A01011200": "해수욕장",
    "A01011700": "호수", "A01020100": "희귀동.식물", "A02010100": "고궁", "A02010600": "민속마을",
    "A02020600": "테마공원", "A02020700": "공원", "A02030100": "농.산.어촌 체험", "A02030200": "전통체험",
    "A02030400": "이색체험", "A02060100": "박물관", "A02060300": "전시관", "A02060500": "미술관/화랑",
    "A02060900": "도서관", "A03021400": "썰매장",
}


# ---------------------------------------------------------------- list edits: leave out / add a kind

# Follow-up edits of the shown list: "물놀이 장소는 빼주세요" / "물놀이 장소도 추천해주세요".
# A kind covers its close relatives; checked on the name, the category (Kakao category_name /
# TourAPI cat3 name) and the grouped entries' names (`includes`).
EXCLUDE_GROUPS = {
    "물놀이": ("물놀이", "워터", "워터파크", "수영장", "해수욕장", "계곡", "물썰매", "아쿠아파크"),
    "키즈카페": ("키즈카페", "실내놀이터", "방방", "트램펄린"),
    "동물원": ("동물원", "아쿠아리움", "동물농장", "주렁주렁"),
    "박물관": ("박물관", "미술관", "전시관", "과학관", "갤러리"),
    "놀이공원": ("놀이공원", "테마파크", "테마공원", "놀이동산"),
    "공원": ("공원",),
    "도서관": ("도서관",),
    "체험농장": ("체험농장", "관광농원", "농.산.어촌"),
    "식물원": ("식물원", "수목원"),
}
EXCLUDE_SETTINGS = {"실내": "indoor", "야외": "outdoor"}
# keyword searches used when a kind the user asked to add is not among the candidates
KIND_SEARCH = {
    "물놀이": ("물놀이장", "워터파크"), "키즈카페": ("키즈카페",), "동물원": ("동물원", "아쿠아리움"),
    "박물관": ("박물관", "과학관"), "놀이공원": ("놀이공원", "테마파크"), "공원": ("공원",),
    "도서관": ("어린이도서관",), "체험농장": ("체험농장",), "식물원": ("수목원", "식물원"),
}


def exclusion_words(term: str) -> tuple[str, ...]:
    return EXCLUDE_GROUPS.get(term, (term,))


def search_words(term: str) -> tuple[str, ...]:
    return KIND_SEARCH.get(term, (term,))


def matches_kind(p: dict, term: str) -> bool:
    """Is this place of the kind `term` (a kind group, 실내/야외, or a place name)?"""
    if term in EXCLUDE_SETTINGS:
        return p.get("indoor_outdoor") == EXCLUDE_SETTINGS[term]
    name, cat = _text(p)
    text = re.sub(r"\s+", "", "".join([name, cat, p.get("category", ""), *[str(n) for n in p.get("includes") or []]]))
    return any(re.sub(r"\s+", "", w) in text for w in exclusion_words(term))


def excluded_by(p: dict, terms: list[str]) -> Optional[str]:
    """The first exclusion term that rules this place out, else None."""
    return next((t for t in terms or [] if matches_kind(p, t)), None)


def _text(p: dict) -> tuple[str, str]:
    cat = p.get("category", "")
    return p.get("name", ""), TOUR_CAT3_NAMES.get(cat, cat)


def outing_grade(p: dict) -> str:
    """A: zoo, theme park, aquarium, arboretum, wetland/eco park, science museum, farm, big park;
    B: museum, hands-on experience, lake, folk village, palace, park;
    C: kids cafe, indoor playground, library, gallery, neighbourhood park, anything else."""
    name, cat = _text(p)
    text = f"{name} {cat}"
    if "kakao:KIDS" in p.get("types", []) or any(w in text for w in SMALL_PARK_WORDS):
        return "C"
    if any(w in text for w in GRADE_A_WORDS):
        return "A"
    if any(w in text for w in GRADE_C_WORDS):
        return "C"
    if "어린이" in name:
        return "A"
    if any(w in text for w in GRADE_B_WORDS):
        return "B"
    return "C"


def kind_tier(p: dict) -> int:
    """Preselection tier: 1 / 2 / 3 for outing grade A / B / C."""
    return {"A": 1, "B": 2, "C": 3}[outing_grade(p)]


def kind_of(p: dict) -> str:
    if "kakao:KIDS" in p.get("types", []):
        return "kids"
    name, cat = _text(p)
    text = f"{name} {cat}"
    for kind, words in KIND_WORDS:
        if any(w in text for w in words):
            return kind
    return "other"


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
