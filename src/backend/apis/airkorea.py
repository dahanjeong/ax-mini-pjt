"""AirKorea fine-dust forecasts (data.go.kr B552584 ArpltnInforInqireSvc).

- dust(lat, lng, date)  Providers.dust -> {pm10_grade, pm25_grade, forecast_source} or {} (no forecast)

Daily forecast (getMinuDustFrcstDspth, today .. +1, +2 after the 17:00 issue): PM10 and
PM2.5 grades 좋음 / 보통 / 나쁨 / 매우나쁨 for 19 forecast regions.
Weekly forecast (getMinuDustWeekFrcstDspth, about +2 .. +5): PM2.5 only, 낮음 / 높음.
Later dates have no forecast ({} -> the card shows 미세먼지 예보 없음).

The forecast region comes from the place's administrative region (Kakao coord2regioncode:
경기 split north/south and 강원 east/west by city, 광주 districts vs 전남), falling back
to the nearest region center when that lookup fails.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from ..agents.place import haversine_km
from ..config import load_env

BASE_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc"
TIMEOUT_S = 5.0
CACHE_TTL_S = 1800
NO_PM10 = "예보 없음"

GYEONGGI_NORTH = ("고양", "파주", "의정부", "양주", "동두천", "포천", "연천", "남양주", "구리", "가평")
GANGWON_EAST = ("강릉", "동해", "삼척", "속초", "고성", "양양", "태백")
GWANGJU_DISTRICTS = ("동구", "서구", "남구", "북구", "광산구")
SIDO = (  # (prefix of region_1depth_name, forecast region)
    ("서울", "서울"), ("인천", "인천"), ("세종", "세종"), ("대전", "대전"), ("대구", "대구"), ("울산", "울산"),
    ("부산", "부산"), ("광주", "광주"), ("제주", "제주"), ("충청북", "충북"), ("충북", "충북"),
    ("충청남", "충남"), ("충남", "충남"), ("전라북", "전북"), ("전북", "전북"), ("전라남", "전남"),
    ("전남", "전남"), ("경상북", "경북"), ("경북", "경북"), ("경상남", "경남"), ("경남", "경남"),
)
REGION_CENTERS = (
    ("서울", 37.5665, 126.9780), ("인천", 37.4563, 126.7052), ("경기북부", 37.8500, 127.0500),
    ("경기남부", 37.2000, 127.1000), ("영서", 37.7000, 128.0000), ("영동", 37.7500, 128.8800),
    ("충북", 36.7500, 127.7000), ("충남", 36.5500, 126.8500), ("세종", 36.4800, 127.2900),
    ("대전", 36.3500, 127.3800), ("전북", 35.7200, 127.1500), ("전남", 34.8500, 126.9000),
    ("광주", 35.1600, 126.8500), ("경북", 36.4000, 128.8000), ("경남", 35.3000, 128.3000),
    ("대구", 35.8700, 128.6000), ("울산", 35.5400, 129.3100), ("부산", 35.1800, 129.0800),
    ("제주", 33.4000, 126.5500),
)


class AirKoreaError(RuntimeError):
    pass


def forecast_region(sido: str, sigungu: str) -> Optional[str]:
    """AirKorea forecast region for an administrative region (None when unknown)."""
    sido, sigungu = sido or "", sigungu or ""
    if sido.startswith("경기"):
        return "경기북부" if sigungu.startswith(GYEONGGI_NORTH) else "경기남부"
    if sido.startswith("강원"):
        return "영동" if sigungu.startswith(GANGWON_EAST) else "영서"
    if "광주" in sido and "전남" in sido:                     # 전남광주통합특별시
        return "광주" if sigungu.split()[0] in GWANGJU_DISTRICTS else "전남"
    for prefix, region in SIDO:
        if sido.startswith(prefix):
            return region
    return None


def nearest_region(lat: float, lng: float) -> str:
    return min(REGION_CENTERS, key=lambda c: haversine_km(lat, lng, c[1], c[2]))[0]


def parse_grades(text: str) -> dict[str, str]:
    """'서울 : 보통,강원영서 : 낮음' -> {'서울': '보통', '영서': '낮음'}"""
    out = {}
    for part in (text or "").split(","):
        if ":" in part:
            name, grade = (x.strip() for x in part.split(":", 1))
            out[re.sub(r"^강원", "", name)] = grade
    return out


class AirKoreaClient:
    def __init__(self, service_key: Optional[str] = None, http: Optional[httpx.Client] = None,
                 region_of: Optional[Callable[[float, float], tuple[str, str]]] = None,
                 today: Callable[[], date] = date.today):
        if service_key is None:
            load_env()
            service_key = os.getenv("PUBLIC_DATA_DECODED_KEY")
        if not service_key:
            raise RuntimeError("PUBLIC_DATA_DECODED_KEY is not set")
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self.key = service_key
        self.region_of = region_of
        self.today = today
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._regions: dict[tuple, str] = {}
        self._lock = threading.Lock()

    def _items(self, op: str, params: dict) -> list[dict]:
        cache_key = (op, tuple(sorted(params.items())))
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return hit[1]
        r = self.http.get(f"/{op}", params={"serviceKey": self.key, "returnType": "json", "numOfRows": 100,
                                            "pageNo": 1, **params})
        r.raise_for_status()
        try:
            data = r.json()["response"]
        except (ValueError, KeyError):
            raise AirKoreaError(f"unexpected response from {op}: {r.text[:200]}")
        if (data.get("header") or {}).get("resultCode") != "00":
            raise AirKoreaError(f"{op}: {data.get('header')}")
        items = (data.get("body") or {}).get("items") or []
        with self._lock:
            self._cache[cache_key] = (time.monotonic(), items)
        return items

    def region(self, lat: float, lng: float) -> str:
        key = (round(lat, 3), round(lng, 3))
        with self._lock:
            if key in self._regions:
                return self._regions[key]
        region = self._lookup_region(lat, lng)
        with self._lock:
            self._regions[key] = region
        return region

    def _lookup_region(self, lat: float, lng: float) -> str:
        if self.region_of is not None:
            try:
                found = forecast_region(*self.region_of(lat, lng))
                if found:
                    return found
            except Exception:
                pass                                         # fall back to the nearest center
        return nearest_region(lat, lng)

    def dust(self, lat: float, lng: float, date_str: str) -> dict:
        region = self.region(lat, lng)
        daily = self._daily(region, date_str)
        if daily:
            return daily
        return self._weekly(region, date_str)

    def _daily(self, region: str, date_str: str) -> dict:
        grades: dict[str, tuple[str, str]] = {}               # code -> (issue time, grade)
        for code in ("PM10", "PM25"):
            items = self._items("getMinuDustFrcstDspth", {"searchDate": self.today().isoformat(), "InformCode": code})
            for it in items:
                if it.get("informCode") != code or it.get("informData") != date_str:
                    continue
                grade = parse_grades(it.get("informGrade", "")).get(region)
                issued = it.get("dataTime", "")
                if grade and (code not in grades or issued > grades[code][0]):
                    grades[code] = (issued, grade)
        if "PM10" not in grades or "PM25" not in grades:
            return {}
        return {"pm10_grade": grades["PM10"][1], "pm25_grade": grades["PM25"][1], "forecast_source": "daily"}

    def _weekly(self, region: str, date_str: str) -> dict:
        for search in (self.today(), self.today() - timedelta(days=1)):   # issued once a day
            items = self._items("getMinuDustWeekFrcstDspth", {"searchDate": search.isoformat()})
            for it in items:
                for n in ("One", "Two", "Three", "Four"):
                    if it.get(f"frcst{n}Dt") == date_str:
                        grade = parse_grades(it.get(f"frcst{n}Cn", "")).get(region)
                        if grade:
                            return {"pm10_grade": NO_PM10, "pm25_grade": grade, "forecast_source": "weekly"}
            if items:
                break
        return {}
