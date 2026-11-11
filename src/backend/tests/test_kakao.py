"""Kakao Local API client, with a mocked HTTP transport (no network)."""
import httpx
import pytest

from backend.agents import place
from backend.apis.kakao import BASE_URL, KakaoClient, is_allowed, place_type


def doc(id_, name, lat, lng, code="AT4", cat="여행 > 관광,명소", road="서울 강남구 테헤란로"):
    return {"id": id_, "place_name": name, "y": str(lat), "x": str(lng), "category_group_code": code,
            "category_name": cat, "road_address_name": road, "address_name": "서울 강남구 역삼동",
            "place_url": f"http://place.map.kakao.com/{id_}"}


def client(handler):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(wrapped))
    return KakaoClient(api_key="test-key", http=http), seen


def json(data, status=200):
    return httpx.Response(status, json=data)


def test_requests_carry_the_rest_api_key():
    k, seen = client(lambda r: json({"documents": [], "meta": {"is_end": True}}))
    k.keyword_search("서울숲")
    assert seen[0].headers["Authorization"] == "KakaoAK test-key"
    assert seen[0].url.path == "/v2/local/search/keyword.json"


def test_geocode_merges_hits_of_the_same_place():
    gangnam = [doc("1", "강남역 2호선", 37.4979, 127.0276, "SW8"),
               doc("2", "강남역 신분당선", 37.4966, 127.0286, "SW8"),
               doc("3", "강남역 지하쇼핑센터", 37.4985, 127.0270, "")]
    k, _ = client(lambda r: json({"documents": gangnam}))
    out = k.geocode("강남역")
    assert out == [{"name": "강남역 2호선", "address": "서울 강남구 테헤란로", "lat": 37.4979, "lng": 127.0276}]


def test_geocode_returns_distinct_places_when_ambiguous():
    city_halls = [doc("1", "서울시청", 37.5663, 126.9779), doc("2", "수원시청", 37.2636, 127.0286),
                  doc("3", "서울시청 서소문청사", 37.5640, 126.9750)]
    k, _ = client(lambda r: json({"documents": city_halls}))
    assert [p["name"] for p in k.geocode("시청")] == ["서울시청", "수원시청"]


def test_geocode_falls_back_to_address_search():
    def handler(r):
        if r.url.path.endswith("keyword.json"):
            return json({"documents": []})
        return json({"documents": [{"address_name": "서울 송파구 올림픽로 300", "y": "37.5125", "x": "127.1025",
                                    "address": {"address_name": "서울 송파구 신천동 29"}}]})

    k, seen = client(handler)
    out = k.geocode("서울시 송파구 올림픽로 300")
    assert out == [{"name": "서울 송파구 올림픽로 300", "address": "서울 송파구 신천동 29",
                    "lat": 37.5125, "lng": 127.1025}]
    assert [r.url.path for r in seen] == ["/v2/local/search/keyword.json", "/v2/local/search/address.json"]


MUSEUM = "문화,예술 > 문화시설 > 박물관"


def test_category_search_caps_radius_pages_and_normalizes():
    def handler(r):
        if r.url.path.endswith("keyword.json"):
            return json({"documents": []})
        code, page = r.url.params["category_group_code"], int(r.url.params["page"])
        docs = [doc(f"{code}{page}{i}", f"{code}-{page}-{i}", 37.5, 127.0, code, cat=MUSEUM) for i in range(2)]
        return json({"documents": docs, "meta": {"is_end": page == 2}})

    k, seen = client(handler)
    out = k.category_search(37.4979, 127.0276, 46.2)
    cat_calls = [r for r in seen if r.url.path.endswith("category.json")]
    kw_calls = [r for r in seen if r.url.path.endswith("keyword.json")]
    assert len(out) == 8 and len(cat_calls) == 4          # 2 categories x 2 pages
    assert [r.url.params["query"] for r in kw_calls] == ["공원", "키즈카페", "동물원"]
    assert {r.url.params["radius"] for r in seen} == {"20000"}
    assert {r.url.params["sort"] for r in seen} == {"distance"}
    p = out[0]
    assert p["source"] == "kakao" and p["type"] == "kakao:AT4" and p["lat"] == 37.5
    # the raw place passes the place agent's normalization
    assert place._norm_place(p, "kakao", (37.4979, 127.0276)) is not None


def test_category_search_keeps_only_allowed_kinds_and_dedupes():
    cat_docs = [doc("1", "어린이박물관", 37.5, 127.0, "CT1", cat=MUSEUM),
                doc("2", "먹자골목", 37.5, 127.0, "AT4", cat="여행 > 관광,명소 > 테마거리 > 먹자골목"),
                doc("3", "소극장", 37.5, 127.0, "CT1", cat="문화,예술 > 문화시설 > 공연장,연극극장"),
                doc("4", "둘레길", 37.5, 127.0, "AT4", cat="여행 > 관광,명소 > 도보여행 > 둘레길")]
    kw_docs = {"공원": [doc("5", "근린공원", 37.5, 127.0, "", cat="여행 > 공원 > 도시근린공원"),
                        doc("1", "어린이박물관", 37.5, 127.0, "CT1", cat=MUSEUM)],
               "키즈카페": [doc("6", "키즈랜드", 37.5, 127.0, "CE7", cat="음식점 > 카페 > 테마카페 > 키즈카페")],
               "동물원": [doc("7", "카페 동물원", 37.5, 127.0, "CE7", cat="음식점 > 카페")]}

    def handler(r):
        if r.url.path.endswith("keyword.json"):
            return json({"documents": kw_docs[r.url.params["query"]]})
        return json({"documents": cat_docs if r.url.params["page"] == "1" else [], "meta": {"is_end": True}})

    k, _ = client(handler)
    out = k.category_search(37.5, 127.0, 10)
    assert [(p["name"], p["type"]) for p in out] == [
        ("어린이박물관", "kakao:CT1"), ("근린공원", "kakao:PARK"), ("키즈랜드", "kakao:KIDS")]
    # every kept place passes the place agent's type filter
    assert all(place._norm_place(p, "kakao", (37.5, 127.0)) for p in out)


def test_allowlist_and_types():
    assert is_allowed("여행 > 관광,명소 > 수목원,식물원")
    assert is_allowed("스포츠,레저 > 스포츠시설 > 눈썰매장")
    assert not is_allowed("문화,예술 > 영화,영상 > 영화관 > CGV")
    assert not is_allowed("여행 > 관광,명소 > 산")
    assert not is_allowed("여행 > 관광,명소 > 테마거리 > 카페거리")
    assert place_type({"category_name": "여행 > 공원 > 생태공원", "category_group_code": ""}) == "kakao:PARK"
    assert place_type({"category_name": "여행 > 관광,명소 > 테마파크", "category_group_code": "AT4"}) == "kakao:AT4"


def test_keyword_search_nearby_and_nationwide():
    water = doc("8", "워터파크", 37.51, 127.01, "AT4", cat="여행 > 관광,명소 > 테마파크 > 워터파크")
    alley = doc("10", "물놀이 골목", 37.51, 127.01, "AT4", cat="여행 > 관광,명소 > 테마거리")
    k, seen = client(lambda r: json({"documents": [water, alley] if "x" in r.url.params
                                     else [doc("9", "서울숲", 37.5444, 127.0374, "", cat="여행 > 공원")]}))
    near = k.keyword_search("물놀이", 37.4979, 127.0276, 5.5)
    assert seen[0].url.params["radius"] == "5500" and seen[0].url.params["x"] == "127.0276"
    assert [p["name"] for p in near] == ["워터파크"]           # nearby candidates pass the allowlist
    out = k.keyword_search("서울숲")
    assert "x" not in seen[1].url.params and out[0]["name"] == "서울숲"


def test_http_errors_raise_so_guarded_marks_the_source_failed():
    k, _ = client(lambda r: json({"errorType": "NotAuthorizedError"}, status=403))
    with pytest.raises(httpx.HTTPStatusError):
        k.category_search(37.5, 127.0, 10)


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setattr("backend.apis.kakao.load_env", lambda: None)
    monkeypatch.delenv("KAKAO_KEY", raising=False)
    with pytest.raises(RuntimeError):
        KakaoClient()


def test_region_prefers_the_administrative_region():
    docs = [{"region_type": "B", "region_1depth_name": "경기도", "region_2depth_name": "가평군 설악면"},
            {"region_type": "H", "region_1depth_name": "경기도", "region_2depth_name": "가평군"}]
    k, seen = client(lambda r: json({"documents": docs}))
    assert k.region(37.75, 127.45) == ("경기도", "가평군")
    assert seen[0].url.path == "/v2/local/geo/coord2regioncode.json"
    assert (seen[0].url.params["x"], seen[0].url.params["y"]) == ("127.45", "37.75")
