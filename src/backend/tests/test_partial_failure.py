"""One external API failing or timing out only blanks its own items."""
import time

import pytest

from backend import tools as rec
from backend.cards import build_cards
from backend.constants import FAIL, FACILITY_KEYS
from backend.tests.test_recommendation import FAC_ALL, make_providers, run, tp

PLACES = [tp(i, f"장소{i}", 3 + i, type_="tourapi:14") for i in range(1, 6)]
OUTDOOR = [tp(1, "야외공원", 3, type_="tourapi:12")]


def boom(*a, **k):
    raise RuntimeError("api down")


def cards(prov, age=30):
    res = run(prov, age=age)
    return res, build_cards(res["result_cards"])


def healthy_baseline():
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    return cards(prov)[1]


def test_baseline_has_no_failures():
    for c in healthy_baseline():
        assert c["failed_sources"] == []
        assert all(f["status"] == "있음" for f in c["facilities"].values())


def test_kma_failure_only_weather():
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    prov.weather = boom
    res, cs = cards(prov)
    assert len(cs) == 5
    for c in cs:
        assert c["weather"] == {"status": FAIL}
        assert c["dust"]["pm10_grade"] == "좋음"
        assert all(f["status"] == "있음" for f in c["facilities"].values())
        assert c["review_summary"] == ["좋아요", "넓어요", "깨끗해요"]
        assert c["failed_sources"] == ["kma"]


def test_airkorea_failure_only_dust():
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    prov.dust = boom
    _, cs = cards(prov)
    for c in cs:
        assert c["dust"] == {"status": FAIL}
        assert c["weather"]["precip_prob_max"] == 10
        assert c["review_summary"] == ["좋아요", "넓어요", "깨끗해요"]
        assert c["failed_sources"] == ["airkorea"]


def test_public_data_failure_only_facilities():
    prov, _ = make_providers(PLACES)
    prov.facilities = boom
    _, cs = cards(prov)
    for c in cs:
        assert all(c["facilities"][k]["status"] == FAIL for k in FACILITY_KEYS)
        assert c["weather"]["precip_prob_max"] == 10
        assert c["dust"]["pm10_grade"] == "좋음"
        assert c["review_summary"] == ["좋아요", "넓어요", "깨끗해요"]
        assert c["failed_sources"] == ["public_data"]


def test_naver_failure_only_reviews_and_naver_facilities():
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    prov.reviews = boom
    _, cs = cards(prov)
    assert len(cs) == 5
    for c in cs:
        assert c["review_summary"] == [FAIL]
        assert all(f["status"] == "있음" for f in c["facilities"].values())  # public data still shown
        assert c["weather"]["precip_prob_max"] == 10
        assert c["failed_sources"] == ["naver"]


def test_naver_failure_blanks_only_unresolved_facilities():
    prov, _ = make_providers(PLACES)  # FAC_ONE: parking is 정보 없음 in public data
    prov.reviews = boom
    _, cs = cards(prov)
    for c in cs:
        assert c["facilities"]["nursing_room"]["status"] == "있음"
        assert c["facilities"]["stroller_rental"]["status"] == "없음"
        assert c["facilities"]["parking"]["status"] == FAIL


def test_llm_failure_keeps_everything_else():
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    prov.llm_judge = boom
    _, cs = cards(prov)
    assert len(cs) == 5
    for c in cs:
        assert c["age_suitability"] == "보통"
        assert c["review_summary"] == [FAIL]
        assert c["weather"]["precip_prob_max"] == 10
        assert all(f["status"] == "있음" for f in c["facilities"].values())


def test_tourapi_failure_uses_kakao_results():
    from backend.tests.test_recommendation import kk

    prov, _ = make_providers(kakao=[kk(i, f"카카오{i}", 3 + i) for i in range(5)])
    prov.tour_search = boom
    res, cs = cards(prov)
    assert len(cs) == 5 and "tourapi" in res["failed_sources"]
    assert all(c["weather"]["precip_prob_max"] == 10 for c in cs)


def test_kakao_failure_uses_tourapi_results():
    prov, _ = make_providers(PLACES)
    prov.kakao_search = boom
    res, cs = cards(prov)
    assert len(cs) == 5 and "kakao" in res["failed_sources"]


def test_llm_indoor_outdoor_failure_does_not_break_card():
    prov, _ = make_providers(OUTDOOR)
    prov.llm_indoor_outdoor = boom
    _, cs = cards(prov)
    assert len(cs) == 1 and cs[0]["weather"]["precip_prob_max"] == 10


@pytest.mark.parametrize("api", ["facilities", "reviews", "weather", "dust"])
def test_timeout_treated_as_failure(monkeypatch, api):
    monkeypatch.setattr(rec, "API_TIMEOUT_S", 0.2)
    prov, _ = make_providers(PLACES, fac={p["name"]: FAC_ALL for p in PLACES})
    setattr(prov, api, lambda *a: time.sleep(1.5))
    t0 = time.monotonic()
    _, cs = cards(prov)
    assert time.monotonic() - t0 < 4
    assert len(cs) == 5
    key = {"facilities": "public_data", "reviews": "naver", "weather": "kma", "dust": "airkorea"}[api]
    for c in cs:
        assert key in c["failed_sources"]
    if api == "weather":
        assert all(c["weather"] == {"status": FAIL} for c in cs)
    if api == "dust":
        assert all(c["dust"] == {"status": FAIL} for c in cs)


def test_timeout_default_is_five_seconds():
    assert rec.API_TIMEOUT_S == 5.0
