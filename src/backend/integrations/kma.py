"""Korea Meteorological Administration forecasts (data.go.kr, VilageFcstInfoService_2.0 /
MidFcstInfoService).

- weather(lat, lng, date)  Providers.weather -> {forecast_source, precip_prob_max, temp_max, temp_min}

Short-term forecast (today .. about +4 days, hourly, on the 5 km grid): the outing
hours 09-18 of the date. Without daytime hours, from +4 days the mid-term forecast is
used; for an earlier date (today after 18:00) the hours left in the day.
Mid-term forecast (+4 .. +10 days): morning/afternoon rain probability for the land
region and min/max temperature for the nearest forecast city.

Responses are cached for CACHE_TTL_S, so a date change for 15 places reuses one
mid-term response per region and one short-term response per grid cell.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from ..core.geo import haversine_km
from ..core.config import load_env

BASE_URL = "https://apis.data.go.kr/1360000"
TIMEOUT_S = 5.0
CACHE_TTL_S = 1800
OUTING_HOURS = range(9, 19)            # 09:00 .. 18:00
SHORT_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
ISSUE_DELAY_MIN = 15                   # a forecast is available a little after its base time
MID_MIN_DAY, MID_MAX_DAY = 4, 10

# (city, lat, lng, mid-term temperature regId, mid-term land regId) - codes checked against the API
MID_CITIES = (
    ("서울", 37.5665, 126.9780, "11B10101", "11B00000"), ("인천", 37.4563, 126.7052, "11B20201", "11B00000"),
    ("수원", 37.2636, 127.0286, "11B20601", "11B00000"), ("파주", 37.7599, 126.7802, "11B20305", "11B00000"),
    ("춘천", 37.8813, 127.7298, "11D10301", "11D10000"), ("원주", 37.3422, 127.9202, "11D10401", "11D10000"),
    ("강릉", 37.7519, 128.8761, "11D20501", "11D20000"), ("대전", 36.3504, 127.3845, "11C20401", "11C20000"),
    ("세종", 36.4800, 127.2890, "11C20404", "11C20000"), ("홍성", 36.6013, 126.6608, "11C20104", "11C20000"),
    ("청주", 36.6424, 127.4890, "11C10301", "11C10000"), ("충주", 36.9910, 127.9259, "11C10101", "11C10000"),
    ("광주", 35.1595, 126.8526, "11F20501", "11F20000"), ("목포", 34.8118, 126.3922, "21F20801", "11F20000"),
    ("여수", 34.7604, 127.6622, "11F20401", "11F20000"), ("전주", 35.8242, 127.1480, "11F10201", "11F10000"),
    ("군산", 35.9676, 126.7369, "21F10501", "11F10000"), ("대구", 35.8714, 128.6014, "11H10701", "11H10000"),
    ("안동", 36.5684, 128.7294, "11H10501", "11H10000"), ("포항", 36.0190, 129.3435, "11H10201", "11H10000"),
    ("부산", 35.1796, 129.0756, "11H20201", "11H20000"), ("울산", 35.5384, 129.3114, "11H20101", "11H20000"),
    ("창원", 35.2280, 128.6811, "11H20301", "11H20000"), ("제주", 33.4996, 126.5312, "11G00201", "11G00000"),
    ("서귀포", 33.2541, 126.5600, "11G00401", "11G00000"),
)


class KMAError(RuntimeError):
    pass


def latlng_to_grid(lat: float, lng: float) -> tuple[int, int]:
    """KMA Lambert conformal conic grid (5 km) used by the short-term forecast."""
    re_km, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0
    re = re_km / grid
    slat1, slat2, olon, olat = slat1 * d, slat2 * d, olon * d, olat * d
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + lat * d * 0.5) ** sn
    theta = (lng * d - olon + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + xo + 0.5), int(ro - ra * math.cos(theta) + yo + 0.5)


def nearest_mid_city(lat: float, lng: float) -> tuple:
    return min(MID_CITIES, key=lambda c: haversine_km(lat, lng, c[1], c[2]))


def short_base(now: datetime) -> tuple[str, str]:
    """Latest short-term issue (base_date, base_time) available at `now`."""
    t = now - timedelta(minutes=ISSUE_DELAY_MIN)
    hours = [h for h in SHORT_BASE_HOURS if h <= t.hour]
    if not hours:
        t -= timedelta(days=1)
        hours = [23]
    return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"


def mid_base(now: datetime) -> datetime:
    """Latest mid-term issue time (06:00 / 18:00) available at `now`."""
    t = now - timedelta(minutes=ISSUE_DELAY_MIN)
    if t.hour >= 18:
        return t.replace(hour=18, minute=0, second=0, microsecond=0)
    if t.hour >= 6:
        return t.replace(hour=6, minute=0, second=0, microsecond=0)
    return (t - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)


class KMAClient:
    def __init__(self, service_key: Optional[str] = None, http: Optional[httpx.Client] = None,
                 now: Callable[[], datetime] = datetime.now):
        if service_key is None:
            load_env()
            service_key = os.getenv("PUBLIC_DATA_DECODED_KEY")
        if not service_key:
            raise RuntimeError("PUBLIC_DATA_DECODED_KEY is not set")
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self.key = service_key
        self.now = now
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- http + cache

    def _items(self, path: str, params: dict) -> list[dict]:
        cache_key = (path, tuple(sorted(params.items())))
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return hit[1]
        r = self.http.get(path, params={"serviceKey": self.key, "pageNo": 1, "dataType": "JSON", **params})
        r.raise_for_status()
        try:
            data = r.json()["response"]
        except (ValueError, KeyError):
            raise KMAError(f"unexpected response from {path}: {r.text[:200]}")
        code = (data.get("header") or {}).get("resultCode")
        if code != "00":
            raise KMAError(f"{path}: {code} {(data.get('header') or {}).get('resultMsg')}")
        items = ((data.get("body") or {}).get("items") or {}).get("item") or []
        items = [items] if isinstance(items, dict) else list(items)
        with self._lock:
            self._cache[cache_key] = (time.monotonic(), items)
        return items

    # ---------------------------------------------------------------- forecast

    def weather(self, lat: float, lng: float, date_str: str) -> dict:
        target = date.fromisoformat(date_str)
        short = self._short_term(lat, lng, target)
        if short is not None:
            return short
        return self._mid_term(lat, lng, target)

    def _short_term(self, lat: float, lng: float, target: date) -> Optional[dict]:
        nx, ny = latlng_to_grid(lat, lng)
        base_date, base_time = short_base(self.now())
        items = self._items("/VilageFcstInfoService_2.0/getVilageFcst", {
            "numOfRows": 1500, "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny})
        day = target.strftime("%Y%m%d")
        rows = [i for i in items if i.get("fcstDate") == day and i.get("category") in ("POP", "TMP")]
        if not rows:
            return None                                   # beyond the short-term range
        outing = [i for i in rows if int(i["fcstTime"][:2]) in OUTING_HOURS]
        if not outing and (target - self.now().date()).days >= MID_MIN_DAY:
            return None                                   # last short-term day without daytime hours
        rows = outing or rows                             # e.g. today after 18:00: the hours left
        pop = [float(i["fcstValue"]) for i in rows if i["category"] == "POP"]
        tmp = [float(i["fcstValue"]) for i in rows if i["category"] == "TMP"]
        if not pop or not tmp:
            return None
        return {"forecast_source": "short_term", "precip_prob_max": int(max(pop)),
                "temp_max": max(tmp), "temp_min": min(tmp)}

    def _mid_term(self, lat: float, lng: float, target: date) -> dict:
        issued = mid_base(self.now())
        n = (target - issued.date()).days
        if not MID_MIN_DAY <= n <= MID_MAX_DAY:
            raise KMAError(f"{target} is outside the forecast range")
        _, _, _, ta_reg, land_reg = nearest_mid_city(lat, lng)
        tm_fc = issued.strftime("%Y%m%d%H%M")
        land = (self._items("/MidFcstInfoService/getMidLandFcst", {"numOfRows": 10, "regId": land_reg, "tmFc": tm_fc})
                or [{}])[0]
        ta = (self._items("/MidFcstInfoService/getMidTa", {"numOfRows": 10, "regId": ta_reg, "tmFc": tm_fc}) or [{}])[0]
        rain = [land.get(k) for k in (f"rnSt{n}Am", f"rnSt{n}Pm", f"rnSt{n}")]
        rain = [float(v) for v in rain if v not in (None, "")]
        tmax, tmin = ta.get(f"taMax{n}"), ta.get(f"taMin{n}")
        if not rain or tmax in (None, "") or tmin in (None, ""):
            raise KMAError(f"no mid-term forecast for day +{n}")
        return {"forecast_source": "mid_term", "precip_prob_max": int(max(rain)),
                "temp_max": float(tmax), "temp_min": float(tmin)}
