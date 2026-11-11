"""Korea Tourism Organization TourAPI 4.0 v2 (KorService2 / KorWithService2, data.go.kr).

- location_search(lat, lng, radius_km)  Providers.tour_search: 관광지(12) · 문화시설(14) ·
                                         레포츠(28) around the departure
- facilities(place)                      Providers.facilities: 수유실 · 유모차 대여 · 주차 from
                                         detailIntro2 + detailWithTour2 (무장애 여행), plus the
                                         `overview` text, which the place agent attaches as the
                                         candidate's description
- keyword_search(q, lat, lng, radius_km) TourAPI side of keyword search

Candidates are kept only when their `cat3` category is in ALLOWED_CAT3 (names in
data/tourapi_categories.json): parks, theme parks, arboretums, museums, galleries,
hands-on experiences, ... - not mountains, valleys, spas, campsites, fishing,
shooting ranges and other activities unsuited to babies.

TourAPI limits `radius` to 20 km. A wider radius is sampled with 7 searches: the
center plus a ring of 6 points, each a 20 km circle, filtered by the real radius.
"""
from __future__ import annotations

import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from ..core.geo import haversine_km
from ..core.config import load_env

BASE_URL = "https://apis.data.go.kr/B551011"
TIMEOUT_S = 5.0
MAX_RADIUS_M = 20000
CONTENT_TYPES = ("12", "14", "28")
ROWS = 30
RING_POINTS = 6
WORKERS = 8
FACILITY_UNKNOWN = "정보 없음"

ALLOWED_CAT3 = frozenset({
    "A01010500",  # 자연생태관광지
    "A01010600",  # 자연휴양림
    "A01010700",  # 수목원
    "A01011200",  # 해수욕장
    "A01011700",  # 호수
    "A01020100",  # 희귀동.식물
    "A02010100",  # 고궁
    "A02010600",  # 민속마을
    "A02020600",  # 테마공원
    "A02020700",  # 공원
    "A02030100",  # 농.산.어촌 체험
    "A02030200",  # 전통체험
    "A02030400",  # 이색체험
    "A02060100",  # 박물관
    "A02060300",  # 전시관
    "A02060500",  # 미술관/화랑
    "A02060900",  # 도서관
    "A03021400",  # 썰매장
})

_NO = re.compile(r"불가|없음|없습니다|미운영|운영\s*안|안\s*됨|X\b")


class TourAPIError(RuntimeError):
    pass


class TourClient:
    def __init__(self, service_key: Optional[str] = None, http: Optional[httpx.Client] = None,
                 app_name: str = "BabyOuting"):
        if service_key is None:
            load_env()
            service_key = os.getenv("PUBLIC_DATA_DECODED_KEY")
        if not service_key:
            raise RuntimeError("PUBLIC_DATA_DECODED_KEY is not set")
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self.common = {"serviceKey": service_key, "MobileOS": "ETC", "MobileApp": app_name, "_type": "json"}

    def _items(self, path: str, params: dict) -> list[dict]:
        r = self.http.get(path, params={**self.common, **params})
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            raise TourAPIError(f"non-JSON response from {path}: {r.text[:200]}")
        header = (data.get("response") or {}).get("header") or {}
        if header.get("resultCode") not in ("0000", "00", None):
            raise TourAPIError(f"{path}: {header.get('resultCode')} {header.get('resultMsg')}")
        items = ((data.get("response") or {}).get("body") or {}).get("items")
        if not items:                              # TourAPI returns "" when there are no items
            return []
        item = items.get("item") if isinstance(items, dict) else items
        if isinstance(item, dict):
            return [item]
        return list(item or [])

    # ---------------------------------------------------------------- places

    def location_search(self, lat: float, lng: float, radius_km: float) -> list[dict]:
        centers = search_centers(lat, lng, radius_km)
        r_m = min(int(radius_km * 1000), MAX_RADIUS_M)
        jobs = [(c, t) for c in centers for t in CONTENT_TYPES]

        def one(job):
            (clat, clng), ctype = job
            return self._items("/KorService2/locationBasedList2", {
                "mapX": clng, "mapY": clat, "radius": r_m, "contentTypeId": ctype,
                "arrange": "E", "numOfRows": ROWS, "pageNo": 1,
            })

        with ThreadPoolExecutor(max_workers=min(WORKERS, len(jobs))) as ex:
            batches = list(ex.map(one, jobs))
        seen, out = set(), []
        for item in (i for b in batches for i in b):
            if item.get("cat3") not in ALLOWED_CAT3:
                continue
            p = _place(item)
            if p["id"] in seen or p["lat"] is None:
                continue
            if haversine_km(lat, lng, p["lat"], p["lng"]) > radius_km:
                continue
            seen.add(p["id"])
            out.append(p)
        return out

    def keyword_search(self, query: str, lat: Optional[float] = None, lng: Optional[float] = None,
                       radius_km: Optional[float] = None) -> list[dict]:
        items = self._items("/KorService2/searchKeyword2", {"keyword": query, "numOfRows": ROWS, "pageNo": 1})
        if lat is not None and lng is not None:           # candidates must pass the allowlist
            items = [i for i in items if i.get("cat3") in ALLOWED_CAT3]
        out = [_place(i) for i in items]                  # nationwide: a reference place can be anything
        if lat is not None and lng is not None:
            out = [p for p in out if p["type"] in {f"tourapi:{t}" for t in CONTENT_TYPES} and p["lat"] is not None
                   and (radius_km is None or haversine_km(lat, lng, p["lat"], p["lng"]) <= radius_km)]
        return out

    # ---------------------------------------------------------------- facilities

    def facilities(self, place: dict) -> dict:
        """{nursing_room, stroller_rental, parking: 있음|없음|정보 없음, overview: str}.
        Places without a TourAPI id get no public data (all 정보 없음)."""
        cid = (place.get("ids") or {}).get("tourapi")
        ctype = next((t.split(":")[1] for t in place.get("types") or [] if t.startswith("tourapi:")), None)
        if not cid or not ctype:
            return {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_intro = ex.submit(self._items, "/KorService2/detailIntro2", {"contentId": cid, "contentTypeId": ctype})
            f_with = ex.submit(self._items, "/KorWithService2/detailWithTour2", {"contentId": cid})
            f_common = ex.submit(self._items, "/KorService2/detailCommon2", {"contentId": cid})
            intro = (f_intro.result() or [{}])[0]
            with_ = (f_with.result() or [{}])[0]
            common = (f_common.result() or [{}])[0]
        return {**facility_status(intro, with_), "overview": _clean(common.get("overview", ""))}


def facility_status(intro: dict, with_: dict) -> dict:
    def judge(*texts: str) -> str:
        texts = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
        if not texts:
            return FACILITY_UNKNOWN
        return "없음" if all(_NO.search(t) for t in texts) else "있음"

    def field(prefix: str) -> list[str]:
        return [v for k, v in intro.items() if k.startswith(prefix) and isinstance(v, str)]

    return {
        "nursing_room": judge(with_.get("lactationroom", "")),
        "stroller_rental": judge(with_.get("stroller", "")) if (with_.get("stroller") or "").strip()
        else judge(*field("chkbabycarriage")),
        "parking": judge(*(field("parking") + [with_.get("parking", "")])),
    }


def search_centers(lat: float, lng: float, radius_km: float) -> list[tuple[float, float]]:
    """The departure, plus a ring of 6 points when the radius exceeds one 20 km search."""
    centers = [(lat, lng)]
    if radius_km <= MAX_RADIUS_M / 1000:
        return centers
    ring_km = max(radius_km - MAX_RADIUS_M / 1000, MAX_RADIUS_M / 1000)
    for i in range(RING_POINTS):
        ang = 2 * math.pi * i / RING_POINTS
        dlat = ring_km * math.cos(ang) / 111.195
        dlng = ring_km * math.sin(ang) / (111.195 * math.cos(math.radians(lat)))
        centers.append((lat + dlat, lng + dlng))
    return centers


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    return re.sub(r"<[^>]+>", "", text).strip()


def _place(i: dict) -> dict:
    """TourAPI item -> raw place for agents.place (type `tourapi:<contenttypeid>`)."""
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "source": "tourapi",
        "id": i.get("contentid"),
        "name": i.get("title", ""),
        "lat": num(i.get("mapy")),
        "lng": num(i.get("mapx")),
        "type": f"tourapi:{i.get('contenttypeid', '')}",
        "address": " ".join(x for x in (i.get("addr1", ""), i.get("addr2", "")) if x).strip(),
        "description": "",                     # filled from `overview` by the facilities lookup
        "category": i.get("cat3") or i.get("lclsSystm3") or "",
        "image": i.get("firstimage", ""),
    }
