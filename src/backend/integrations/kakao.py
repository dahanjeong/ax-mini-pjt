"""Kakao Local API (https://dapi.kakao.com, header `Authorization: KakaoAK <REST key>`).

- geocode(query)                          departure lookup for the supervisor (a subway
                                           station named like the query is taken as is)
- region(lat, lng)                        (시도, 시군구) for the fine-dust forecast region
- category_search(lat, lng, radius_km)    Providers.kakao_search: AT4 관광명소 / CT1 문화시설
                                           + keyword searches for parks, kids cafes and zoos
                                           (Kakao files parks outside AT4/CT1), filtered
                                           by an allowlist of category names
- keyword_search(q, lat, lng, radius_km)  Providers.keyword_search (preference keywords;
                                           nationwide when lat/lng are None, for reference
                                           places; both filtered by the allowlist)
- drive_minutes(o_lat, o_lng, d_lat, d_lng, departure_time)
                                           Providers.drive_minutes: expected car travel time when
                                           leaving at departure_time (Kakao Mobility future
                                           directions, same REST key,
                                           https://apis-navi.kakaomobility.com)

Kakao limits `radius` to 20 km and returns at most 45 documents per query
(3 pages x 15); wider areas are covered by TourAPI.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import httpx

from ..core.geo import haversine_km
from ..core.config import load_env

BASE_URL = "https://dapi.kakao.com"
NAVI_URL = "https://apis-navi.kakaomobility.com"
TIMEOUT_S = 5.0
MAX_RADIUS_M = 20000
PAGE_SIZE = 15
CATEGORY_PAGES = 2
CATEGORIES = ("AT4", "CT1")
EXTRA_QUERIES = ("공원", "키즈카페", "동물원")

# A place is kept only when one segment of its `category_name`
# ("여행 > 관광,명소 > 테마파크") contains one of these words. This drops theme streets,
# food alleys, walking trails, theaters, cinemas, mountains, valleys, hot springs, ...
ALLOWED_CATEGORY_WORDS = (
    "공원", "키즈카페", "놀이", "어린이", "체험", "테마파크", "워터파크", "유원지",
    "박물관", "미술관", "전시관", "과학관", "아쿠아리움", "동물원", "수목원", "식물원",
    "숲", "호수", "관광농원", "도예촌", "눈썰매장", "해수욕장", "휴양림", "생태",
)
SAME_PLACE_KM = 1.5          # geocode results this close to the top hit are the same place
MAX_GEOCODE_CANDIDATES = 5


class KakaoClient:
    def __init__(self, api_key: Optional[str] = None, http: Optional[httpx.Client] = None,
                 navi_http: Optional[httpx.Client] = None):
        if api_key is None:
            load_env()
            api_key = os.getenv("KAKAO_KEY")
        if not api_key:
            raise RuntimeError("KAKAO_KEY is not set")
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self.navi_http = navi_http or httpx.Client(base_url=NAVI_URL, timeout=TIMEOUT_S)
        self.headers = {"Authorization": f"KakaoAK {api_key}"}

    def _get(self, path: str, params: dict) -> dict:
        r = self.http.get(path, params={k: v for k, v in params.items() if v is not None},
                          headers=self.headers)
        r.raise_for_status()
        return r.json()

    # ---------------------------------------------------------------- departure

    def geocode(self, query: str) -> list[dict]:
        """[{name, address, lat, lng}]; one item when the hits are all the same place,
        several (one per distinct place) when the name is ambiguous, [] when not found."""
        docs = self._get("/v2/local/search/keyword.json", {"query": query, "size": PAGE_SIZE}).get("documents") or []
        if not docs:
            docs = self._get("/v2/local/search/address.json", {"query": query}).get("documents") or []
        if docs and _is_named_station(docs[0], query):
            # "판교역" -> 판교역 신분당선: a subway station named like the query is what was meant
            # (Kakao still lists 판교역(충남), a rail station far away)
            hit = _departure(docs[0])
            return [hit] if hit else []
        hits = [_departure(d) for d in docs]
        hits = [h for h in hits if h]
        distinct: list[dict] = []
        for h in hits:
            if not any(haversine_km(h["lat"], h["lng"], d["lat"], d["lng"]) <= SAME_PLACE_KM for d in distinct):
                distinct.append(h)
        return distinct[:MAX_GEOCODE_CANDIDATES]

    def region(self, lat: float, lng: float) -> tuple[str, str]:
        """(시도, 시군구) of a point, e.g. ('경기도', '가평군') - administrative ('H') region."""
        docs = self._get("/v2/local/geo/coord2regioncode.json", {"x": lng, "y": lat}).get("documents") or []
        doc = next((d for d in docs if d.get("region_type") == "H"), docs[0] if docs else None)
        if not doc:
            raise ValueError(f"no region for {lat},{lng}")
        return doc.get("region_1depth_name", ""), doc.get("region_2depth_name", "")

    # ---------------------------------------------------------------- travel time

    def drive_minutes(self, o_lat: float, o_lng: float, d_lat: float, d_lng: float,
                      departure_time: datetime) -> float:
        """Expected car travel time in minutes when leaving at `departure_time` (KST; future
        traffic, recommended route). Raises when no route is found."""
        r = self.navi_http.get("/v1/future/directions", params={
            "origin": f"{o_lng},{o_lat}", "destination": f"{d_lng},{d_lat}",
            "departure_time": departure_time.strftime("%Y%m%d%H%M"), "summary": "true",
        }, headers=self.headers)
        r.raise_for_status()
        route = (r.json().get("routes") or [{}])[0]
        if route.get("result_code") != 0:
            raise ValueError(f"no route: {route.get('result_code')} {route.get('result_msg')}")
        return route["summary"]["duration"] / 60.0

    # ---------------------------------------------------------------- places

    def category_search(self, lat: float, lng: float, radius_km: float) -> list[dict]:
        radius_m = min(int(radius_km * 1000), MAX_RADIUS_M)
        docs: list[dict] = []
        for code in CATEGORIES:
            for page in range(1, CATEGORY_PAGES + 1):
                data = self._get("/v2/local/search/category.json", {
                    "category_group_code": code, "x": lng, "y": lat, "radius": radius_m,
                    "sort": "distance", "page": page, "size": PAGE_SIZE,
                })
                docs += data.get("documents") or []
                if (data.get("meta") or {}).get("is_end", True):
                    break
        for q in EXTRA_QUERIES:
            docs += self._get("/v2/local/search/keyword.json", {
                "query": q, "x": lng, "y": lat, "radius": radius_m, "sort": "distance", "size": PAGE_SIZE,
            }).get("documents") or []
        seen: set = set()
        out = []
        for d in docs:
            if d.get("id") in seen or not is_allowed(d.get("category_name", "")):
                continue
            seen.add(d.get("id"))
            out.append(_place(d))
        return out

    def keyword_search(self, query: str, lat: Optional[float] = None, lng: Optional[float] = None,
                       radius_km: Optional[float] = None) -> list[dict]:
        params: dict[str, Any] = {"query": query, "size": PAGE_SIZE}
        if lat is not None and lng is not None:
            params.update({"x": lng, "y": lat, "sort": "accuracy"})
            if radius_km is not None:
                params["radius"] = min(int(radius_km * 1000), MAX_RADIUS_M)
        docs = self._get("/v2/local/search/keyword.json", params).get("documents") or []
        # candidates and reference places ("서울숲 같은 곳") must both be outing places:
        # nationwide, the allowlist drops parking lots, ticket booths and same-named shops
        # ("우주정거장" the toy store) that would otherwise be offered as the reference
        docs = [d for d in docs if is_allowed(d.get("category_name", ""))]
        return [_place(d) for d in docs]


SUBWAY_STATION = "SW8"


def _is_named_station(d: dict, query: str) -> bool:
    """Top geocode hit is a subway station whose name starts with the query ('판교역 신분당선')."""
    q = "".join((query or "").split())
    name = "".join((d.get("place_name") or "").split())
    return d.get("category_group_code") == SUBWAY_STATION and bool(q) and name.startswith(q)


def _departure(d: dict) -> Optional[dict]:
    try:
        lat, lng = float(d["y"]), float(d["x"])
    except (KeyError, TypeError, ValueError):
        return None
    name = d.get("place_name") or d.get("address_name") or ""
    address = d.get("road_address_name") or d.get("address_name") or ""
    if isinstance(d.get("address"), dict):          # address.json documents
        address = d["address"].get("address_name") or address
    return {"name": name, "address": address, "lat": lat, "lng": lng}


def is_allowed(category_name: str) -> bool:
    segments = [s.strip() for s in (category_name or "").split(">")]
    return any(w in s for s in segments for w in ALLOWED_CATEGORY_WORDS)


def place_type(d: dict) -> str:
    """kakao:PARK / kakao:KIDS for parks and kids cafes, else kakao:<category_group_code>."""
    segments = [s.strip() for s in (d.get("category_name") or "").split(">")]
    if "키즈카페" in segments:
        return "kakao:KIDS"
    if len(segments) > 1 and segments[1] == "공원":
        return "kakao:PARK"
    code = d.get("category_group_code") or ""
    return f"kakao:{code}"


def _place(d: dict) -> dict:
    """Kakao document -> raw place for agents.place."""
    return {
        "source": "kakao",
        "id": d.get("id"),
        "name": d.get("place_name", ""),
        "lat": float(d["y"]) if d.get("y") else None,
        "lng": float(d["x"]) if d.get("x") else None,
        "type": place_type(d),
        "address": d.get("road_address_name") or d.get("address_name") or "",
        "description": d.get("category_name", ""),
        "url": d.get("place_url", ""),
    }
