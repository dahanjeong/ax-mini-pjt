"""NAVER Search API (NAVER API HUB) client, with a mocked HTTP transport (no network)."""
import httpx
import pytest

from backend.integrations.naver import BASE_URL, MAX_REVIEWS, NaverClient, clean, mentions, name_keys


def item(title, desc, link, date="20260801"):
    return {"title": title, "description": desc, "link": link, "postdate": date}


def client(handler):
    seen = []

    def wrapped(r):
        seen.append(r)
        return handler(r)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(wrapped))
    return NaverClient("id", "secret", http=http), seen


def test_headers_query_and_both_sources():
    nv, seen = client(lambda r: httpx.Response(200, json={"items": []}))
    assert nv.reviews({"name": "서울대공원"}) == []
    assert {r.url.path for r in seen} == {"/search/v1/blog", "/search/v1/cafearticle"}
    assert str(seen[0].url).startswith("https://naverapihub.apigw.ntruss.com/")
    r = seen[0]
    assert r.headers["X-NCP-APIGW-API-KEY-ID"] == "id" and r.headers["X-NCP-APIGW-API-KEY"] == "secret"
    assert r.url.params["query"] == "서울대공원 아기랑" and r.url.params["sort"] == "sim"   # no address


def test_query_carries_the_city_or_district():
    """Round 1 #2 (2nd run): "패밀리가든 아기랑" returned hotels in 강릉 and 제주."""
    nv, seen = client(lambda r: httpx.Response(200, json={"items": []}))
    nv.reviews({"name": "패밀리가든", "address": "경기 성남시 분당구 판교역로146번길 20"})
    assert seen[0].url.params["query"] == "성남 패밀리가든 아기랑"


@pytest.mark.parametrize("address,word", [
    ("경기 성남시 분당구 판교역로 146", "성남"), ("서울 송파구 올림픽로 240", "송파"),
    ("경기도 가평군 상면 행현리", "가평"), ("서울특별시 성동구 뚝섬로 273", "성동"),
    ("세종특별자치시 다솜로 261", ""), ("", ""),
])
def test_region_word(address, word):
    from backend.integrations.naver import region_word
    assert region_word(address) == word


def test_cleans_filters_dedupes_and_interleaves():
    blog = [item("<b>서울대공원</b> 아기랑 다녀왔어요", "유모차 끌고 다니기 좋아요 &amp; 수유실 있음", "b1"),
            item("주말 나들이", "서울 대공원 동물원 후기", "b2"),                      # spaced name still matches
            item("맛집 추천", "강남 파스타 맛집", "b3"),                               # unrelated -> dropped
            item("서울대공원 후기", "", "b4")]                                        # empty snippet -> dropped
    cafe = [item("서울대공원 질문", "18개월 아기 서울대공원 괜찮나요", "c1"),
            item("<b>서울대공원</b> 아기랑 다녀왔어요", "같은 글", "b1")]               # same link -> dropped

    def handler(r):
        return httpx.Response(200, json={"items": blog if "blog" in r.url.path else cafe})

    nv, _ = client(handler)
    out = nv.reviews({"name": "서울대공원"})
    assert [(x["source"], x["link"]) for x in out] == [("blog", "b1"), ("cafe", "c1"), ("blog", "b2")]
    assert out[0]["title"] == "서울대공원 아기랑 다녀왔어요"
    assert out[0]["snippet"] == "유모차 끌고 다니기 좋아요 & 수유실 있음"
    assert set(out[0]) == {"title", "snippet", "link", "source", "date"}


def test_caps_at_max_reviews():
    many = [item(f"웅진플레이도시 후기 {i}", "웅진플레이도시 좋아요", f"l{i}") for i in range(10)]
    nv, _ = client(lambda r: httpx.Response(200, json={"items": [
        {**m, "link": ("b" if "blog" in r.url.path else "c") + m["link"]} for m in many]}))
    assert len(nv.reviews({"name": "웅진플레이도시"})) == MAX_REVIEWS


def test_name_keys_and_mentions():
    assert name_keys("국립중앙박물관 어린이박물관") == ["국립중앙박물관어린이박물관", "국립중앙박물관", "어린이박물관"]
    assert name_keys("어린이대공원 (서울)") == ["어린이대공원"]
    assert mentions("서울 대공원 다녀옴", name_keys("서울대공원"))
    assert not mentions("대공원 다녀옴", name_keys("서울대공원"))
    assert clean("<b>a</b>  &lt;b&gt; ") == "a <b>"


def test_auth_error_raises():
    nv, _ = client(lambda r: httpx.Response(401, json={"errorCode": "024"}))
    with pytest.raises(httpx.HTTPStatusError):
        nv.reviews({"name": "x"})


def test_missing_keys_are_reported(monkeypatch):
    monkeypatch.setattr("backend.integrations.naver.load_env", lambda: None)
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_KEY", raising=False)
    with pytest.raises(RuntimeError):
        NaverClient()
