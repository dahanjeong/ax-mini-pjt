"""TourAPI client, with a mocked HTTP transport (no network)."""
import json as jsonlib
from pathlib import Path

import httpx
import pytest

from backend.agents import place
from backend.apis.tourapi import (
    ALLOWED_CAT3, BASE_URL, TourAPIError, TourClient, facility_status, search_centers,
)
from backend.tests.test_recommendation import make_providers, tp

ROOT = Path(__file__).resolve().parents[3]
PARK, MOUNTAIN, MUSEUM = "A02020700", "A01010400", "A02060100"


def item(cid, title, lat, lng, ctype="12", cat3=PARK):
    return {"contentid": cid, "title": title, "mapy": str(lat), "mapx": str(lng), "contenttypeid": ctype,
            "cat3": cat3, "addr1": "서울 강남구", "addr2": "1층", "firstimage": ""}


def body(items, code="0000"):
    if items == "":
        payload = ""
    elif isinstance(items, dict):
        payload = {"item": items}
    else:
        payload = {"item": items}
    return httpx.Response(200, json={"response": {"header": {"resultCode": code, "resultMsg": "OK"},
                                                  "body": {"items": payload}}})


def client(handler):
    seen = []

    def wrapped(r):
        seen.append(r)
        return handler(r)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(wrapped))
    return TourClient(service_key="test-key", http=http), seen


def test_common_params_and_item_shapes():
    tc, seen = client(lambda r: body(item("1", "공원", 37.5, 127.0)))      # single item comes as a dict
    out = tc.keyword_search("공원")
    q = seen[0].url.params
    assert q["serviceKey"] == "test-key" and q["MobileOS"] == "ETC" and q["_type"] == "json"
    assert out[0]["name"] == "공원" and out[0]["type"] == "tourapi:12" and out[0]["address"] == "서울 강남구 1층"
    tc, _ = client(lambda r: body(""))                                      # no items -> ""
    assert tc.keyword_search("없음") == []


def test_error_result_code_raises():
    tc, _ = client(lambda r: body([], code="30"))
    with pytest.raises(TourAPIError):
        tc.keyword_search("x")
    tc, _ = client(lambda r: httpx.Response(200, text="<OpenAPI_ServiceResponse>SERVICE KEY IS NOT REGISTERED"))
    with pytest.raises(TourAPIError):
        tc.keyword_search("x")


def test_search_centers():
    assert len(search_centers(37.5, 127.0, 15)) == 1
    centers = search_centers(37.5, 127.0, 46.2)
    assert len(centers) == 7
    ring = [place.haversine_km(37.5, 127.0, lat, lng) for lat, lng in centers[1:]]
    assert all(abs(d - 26.2) < 0.5 for d in ring)


def test_location_search_filters_categories_radius_and_duplicates():
    near_park = item("1", "근린공원", 37.51, 127.0)
    mountain = item("2", "관악산", 37.52, 127.0, cat3=MOUNTAIN)
    museum = item("3", "어린이박물관", 37.53, 127.0, ctype="14", cat3=MUSEUM)
    too_far = item("4", "먼공원", 38.5, 127.0)

    def handler(r):
        t = r.url.params["contentTypeId"]
        return body([museum] if t == "14" else [near_park, mountain, too_far, near_park])

    tc, seen = client(handler)
    out = tc.location_search(37.5, 127.0, 46.2)
    assert sorted(p["name"] for p in out) == ["근린공원", "어린이박물관"]
    assert len(seen) == 7 * 3                                   # 7 centers x 3 content types
    assert {r.url.params["radius"] for r in seen} == {"20000"}
    assert all(place._norm_place(p, "tourapi", (37.5, 127.0)) for p in out)


def test_keyword_search_nearby_applies_allowlist_nationwide_does_not():
    tc, _ = client(lambda r: body([item("1", "물놀이공원", 37.51, 127.0), item("2", "물놀이 산", 37.51, 127.0, cat3=MOUNTAIN)]))
    assert [p["name"] for p in tc.keyword_search("물놀이", 37.5, 127.0, 10)] == ["물놀이공원"]
    assert len(tc.keyword_search("물놀이")) == 2


INTRO = {"contentid": "1", "parkingculture": "", "parkingfee": "기본 30분 900원", "chkbabycarriageculture": ""}
WITH = {"lactationroom": "수유실 있음(1층)", "stroller": "대여 가능(1층)", "parking": "장애인 주차구역 있음"}


def test_facility_status_rules():
    assert facility_status(INTRO, WITH) == {"nursing_room": "있음", "stroller_rental": "있음", "parking": "있음"}
    assert facility_status({}, {}) == {"nursing_room": "정보 없음", "stroller_rental": "정보 없음", "parking": "정보 없음"}
    assert facility_status({"parking": "주차 불가"}, {"lactationroom": "없음"}) == {
        "nursing_room": "없음", "stroller_rental": "정보 없음", "parking": "없음"}
    # no 무장애 stroller info -> the intro's chkbabycarriage field decides
    assert facility_status({"chkbabycarriage": "가능"}, {})["stroller_rental"] == "있음"


def test_facilities_calls_three_detail_endpoints_and_returns_overview():
    def handler(r):
        path = r.url.path
        if path.endswith("detailIntro2"):
            assert r.url.params["contentTypeId"] == "14"
            return body([INTRO])
        if path.endswith("detailWithTour2"):
            return body([WITH])
        return body([{"overview": "어린이박물관입니다.<br>유모차 이용 가능"}])

    tc, seen = client(handler)
    out = tc.facilities({"name": "박물관", "ids": {"tourapi": "129703"}, "types": ["tourapi:14"]})
    assert out["nursing_room"] == "있음" and out["overview"] == "어린이박물관입니다.\n유모차 이용 가능"
    assert {r.url.path.rsplit("/", 1)[1] for r in seen} == {"detailIntro2", "detailWithTour2", "detailCommon2"}
    assert "/KorWithService2/" in next(str(r.url) for r in seen if "detailWithTour2" in str(r.url))
    assert tc.facilities({"name": "kakao only", "ids": {"kakao": "1"}, "types": ["kakao:AT4"]}) == {}


def test_overview_becomes_the_candidate_description():
    prov, _ = make_providers([tp(1, "어린이박물관", 1, "tourapi:14")])
    prov.facilities = lambda p: {"nursing_room": "있음", "overview": "아이들이 체험하는 박물관입니다."}
    out = place.run(place.build_graph(prov), departure={"lat": 37.5, "lng": 127.0}, age_months=30,
                    travels_during_nap=False)
    assert out["candidates"][0]["description"] == "아이들이 체험하는 박물관입니다."


def test_category_table_covers_the_allowlist():
    table = jsonlib.loads((ROOT / "data" / "tourapi_categories.json").read_text(encoding="utf-8"))["cat3"]
    assert ALLOWED_CAT3 <= set(table)
    assert table[PARK].endswith("공원")


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setattr("backend.apis.tourapi.load_env", lambda: None)
    monkeypatch.delenv("PUBLIC_DATA_DECODED_KEY", raising=False)
    with pytest.raises(RuntimeError):
        TourClient()
