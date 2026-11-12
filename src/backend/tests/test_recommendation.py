import time
from datetime import date

import pytest

from backend.agent import Deps, build_graph, recommendation_turn
from backend.supervisor.pipeline import recommend
from backend.agents.environment import evaluate_bad_day
from backend.agents.candidates import merge_places
from backend.agents.place import max_drive_hours, radius_km_for
from backend.tools import Providers

DEP = {"name": "강남역", "address": "서울", "lat": 37.5, "lng": 127.0}
DATE = "2026-11-12"


def at_km(km):
    """Latitude offset giving a straight-line distance of `km` north of DEP."""
    return 37.5 + km / 111.195


def tp(i, name, km, type_="tourapi:14", **kw):
    return {"id": f"T{i}", "name": name, "lat": at_km(km), "lng": 127.0, "type": type_, **kw}


def kk(i, name, km, type_="kakao:CT1", **kw):
    return {"id": f"K{i}", "name": name, "lat": at_km(km), "lng": 127.0, "type": type_, **kw}


FAC_ALL = {"nursing_room": "있음", "stroller_rental": "있음", "parking": "있음"}
FAC_ONE = {"nursing_room": "있음", "stroller_rental": "없음", "parking": "정보 없음"}
FAC_NONE = {"nursing_room": "없음", "stroller_rental": "정보 없음", "parking": "정보 없음"}
GOOD_W = {"forecast_source": "short_term", "precip_prob_max": 10, "temp_max": 20, "temp_min": 8}
GOOD_D = {"pm10_grade": "좋음", "pm25_grade": "보통"}


def km_of(lat):
    return round((lat - 37.5) * 111.195, 1)


def make_providers(tour=(), kakao=(), suit=None, fac=None, weather=None, dust=None, io=None, sleep=0.0,
                   drive=None):
    """`drive`: {km: minutes} overrides (a value raising Exception = API failure); other places
    take km * 60 / 45 minutes. drive=False -> no drive-time provider."""
    suit, fac, weather, dust, io = suit or {}, fac or {}, weather or {}, dust or {}, io or {}
    calls = {"judged": [], "io": [], "drive": []}
    overrides = drive or {}

    def drive_minutes(o_lat, o_lng, d_lat, d_lng, departure_time):
        km = km_of(d_lat)
        calls["drive"].append(km)
        calls.setdefault("departures", []).append(departure_time)
        v = overrides.get(km, km * 60 / 45)
        if isinstance(v, Exception):
            raise v
        return v

    def judge(place, age, reviews):
        time.sleep(sleep)
        calls["judged"].append(place["name"])
        return {
            "age_suitability": suit.get(place["name"], "적합"),
            "summary": ["좋아요", "넓어요", "깨끗해요"],
            "facility_mentions": {},
        }

    def classify(place, reviews):
        calls["io"].append(place["name"])
        return io.get(place["name"], "outdoor")

    def sleeper(v):
        def f(*a):
            time.sleep(sleep)
            return v

        return f

    prov = Providers(
        tour_search=lambda lat, lng, r: list(tour),
        kakao_search=lambda lat, lng, r: list(kakao),
        facilities=lambda p: (time.sleep(sleep), fac.get(p["name"], FAC_ONE))[1],
        reviews=lambda p: (time.sleep(sleep), [{"title": "t", "snippet": "s"}] * 5)[1],
        weather=lambda lat, lng, d: (time.sleep(sleep), weather.get(round(lat, 3), GOOD_W))[1],
        dust=lambda lat, lng, d: (time.sleep(sleep), dust.get(round(lat, 3), GOOD_D))[1],
        llm_judge=judge,
        llm_indoor_outdoor=classify,
        drive_minutes=None if drive is False else drive_minutes,
    )
    return prov, calls


def run(prov, age=30, nap=False):
    return recommend(prov, age_months=age, departure=DEP, outing_date=DATE, travels_during_nap=nap)


def names(res):
    return [c["name"] for c in res["result_cards"]]


# ------------------------------------------------------------------ radius

@pytest.mark.parametrize(
    "age,nap,hours",
    [(0, False, 1), (6, False, 1), (7, False, 1), (12, False, 1), (13, False, 1.5), (24, False, 1.5),
     (24, True, 1.5), (25, False, 2), (72, False, 2), (6, True, 2), (12, True, 2), (13, True, 2.5),
     (23, True, 2.5), (23, False, 1.5)],
)
def test_max_drive_hours_by_age_and_nap(age, nap, hours):
    assert max_drive_hours(age, nap) == hours


def test_radius_formula():
    assert radius_km_for(2) == pytest.approx(2 * 40 / 1.3)
    assert radius_km_for(1) == pytest.approx(30.769, abs=1e-3)


def test_places_outside_radius_dropped_and_other_types_dropped():
    # 12 months, no nap -> 1h -> 30.77 km
    tour = [tp(i, f"장소{i}", 5 + i) for i in range(5)] + [tp(9, "너무멀어", 40)]
    tour.append(tp(8, "음식점", 3, type_="tourapi:39"))
    kakao = [kk(7, "카페", 3, type_="kakao:CE7")]
    prov, _ = make_providers(tour, kakao)
    res = run(prov, age=12)
    assert res["radius_km"] == pytest.approx(30.769, abs=1e-3)
    assert "너무멀어" not in names(res) and "음식점" not in names(res) and "카페" not in names(res)
    assert len(names(res)) == 5 and not res["radius_expanded"]


def test_nap_extension_widens_radius():
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    assert run(prov, age=10, nap=True)["radius_km"] == pytest.approx(2 * 40 / 1.3)
    assert run(prov, age=24, nap=True)["radius_km"] == pytest.approx(1.5 * 40 / 1.3)


# ------------------------------------------------------------------ merge

def test_duplicates_merged_by_name_and_distance():
    tour = [tp(1, "서울 어린이 대공원", 10, type_="tourapi:12")]
    kakao = [
        kk(1, "서울어린이대공원 (정문)", 10.05, type_="kakao:AT4"),  # ~50 m away, same name after normalizing
        kk(2, "서울어린이대공원", 10.5, type_="kakao:AT4"),          # 500 m away -> distinct
    ]
    merged = merge_places(
        [dict(p, ids={"tourapi": 1}, place_source=["tourapi"], types=[p["type"]]) for p in tour]
        + [dict(p, ids={"kakao": p["id"]}, place_source=["kakao"], types=[p["type"]]) for p in kakao]
    )
    assert len(merged) == 2
    both = [m for m in merged if len(m["place_source"]) == 2]
    assert len(both) == 1 and both[0]["place_source"] == ["kakao", "tourapi"]


def test_merge_end_to_end_keeps_one_card():
    tour = [tp(1, "국립어린이박물관", 10)] + [tp(i, f"장소{i}", 10 + i) for i in range(2, 6)]
    kakao = [kk(1, "국립 어린이 박물관", 10.03)]
    prov, calls = make_providers(tour, kakao)
    res = run(prov)
    assert names(res).count("국립어린이박물관") == 1
    assert sum("어린이" in n for n in calls["judged"]) == 1
    card = next(c for c in res["result_cards"] if c["name"] == "국립어린이박물관")
    assert card["place_source"] == ["kakao", "tourapi"]


def test_similar_names_but_far_apart_not_merged():
    tour = [tp(1, "롯데월드", 10)]
    kakao = [kk(1, "롯데월드", 12)]
    prov, calls = make_providers(tour, kakao)
    assert len(calls["judged"]) == 0
    res = run(prov)
    assert names(res) == ["롯데월드", "롯데월드"]


# ------------------------------------------------------------------ exclusion & ranking

def test_unsuitable_places_excluded():
    tour = [tp(i, f"장소{i}", 5 + i) for i in range(7)]
    prov, _ = make_providers(tour, suit={"장소0": "부적합", "장소1": "부적합"})
    res = run(prov)
    assert "장소0" not in names(res) and "장소1" not in names(res)
    assert len(names(res)) == 5


def test_ranking_suitability_then_facilities_then_distance():
    tour = [
        tp(1, "보통-가까움-시설3", 5), tp(2, "적합-멀리-시설0", 40), tp(3, "적합-중간-시설1", 20),
        tp(4, "적합-중간-시설3", 25), tp(5, "적합-가까움-시설3", 10), tp(6, "적합-가까움-시설3b", 8),
    ]
    prov, _ = make_providers(
        tour,
        suit={"보통-가까움-시설3": "보통"},
        fac={
            "보통-가까움-시설3": FAC_ALL, "적합-멀리-시설0": FAC_NONE, "적합-중간-시설1": FAC_ONE,
            "적합-중간-시설3": FAC_ALL, "적합-가까움-시설3": FAC_ALL, "적합-가까움-시설3b": FAC_ALL,
        },
    )
    res = run(prov)
    assert names(res) == ["적합-가까움-시설3b", "적합-가까움-시설3", "적합-중간-시설3", "적합-중간-시설1", "적합-멀리-시설0"]
    assert res["result_cards"][0]["facility_count"] == 3
    assert res["result_cards"][4]["facility_count"] == 0
    assert "보통-가까움-시설3" not in names(res)  # sixth


def test_missing_and_failed_facility_info_count_as_zero():
    from backend.supervisor.pipeline import _count

    assert _count({"a": {"status": "정보를 불러오지 못함"}, "nursing_room": {"status": "있음"},
                   "parking": {"status": "정보 없음"}, "stroller_rental": {"status": "없음"}}) == 1


def test_preselect_keeps_15_spread_over_distance_bands():
    tour = [tp(i, f"장소{i:02d}", 2 + i) for i in range(20)]          # 2 .. 21 km, all the same kind
    prov, calls = make_providers(tour)
    res = run(prov)
    judged = sorted(calls["judged"])
    assert len(judged) == 15
    # 0-5 km: 3 places, 20+ km: 2 places -> both bands fully kept; 5-20 km fills the rest, nearest first
    assert {"장소00", "장소01", "장소02", "장소18", "장소19"} <= set(judged)
    assert names(res)[:3] == ["장소00", "장소01", "장소02"]


# ------------------------------------------------------------------ bad days

@pytest.mark.parametrize(
    "w,d,warn",
    [
        ({"precip_prob_max": 60}, {}, ["강수"]),
        ({"precip_prob_max": 59}, {}, []),
        ({}, {"pm10_grade": "나쁨"}, ["미세먼지"]),
        ({}, {"pm25_grade": "매우나쁨"}, ["미세먼지"]),
        ({}, {"pm10_grade": "보통", "pm25_grade": "좋음"}, []),
        ({"temp_max": 33}, {}, ["폭염"]),
        ({"temp_max": 32.9}, {}, []),
        ({"temp_min": -5}, {}, ["한파"]),
        ({"temp_min": -4.9}, {}, []),
    ],
)
def test_bad_day_thresholds(w, d, warn):
    bad, warnings = evaluate_bad_day(w, d)
    assert warnings == warn and bad == bool(warn)


def test_outdoor_goes_below_indoor_on_bad_day_with_warning():
    # outdoor (tourapi:12) is closer and better-equipped but its location has rain
    tour = [
        tp(1, "야외공원", 5, type_="tourapi:12"),
        tp(2, "실내박물관", 20, type_="tourapi:14"),
        tp(3, "실내도서관", 25, type_="tourapi:14"),
    ]
    rainy = {round(at_km(5), 3): {"forecast_source": "mid_term", "precip_prob_max": 80, "temp_max": 15, "temp_min": 5}}
    prov, _ = make_providers(tour, fac={"야외공원": FAC_ALL}, weather=rainy, io={"야외공원": "outdoor"})
    res = run(prov)
    assert names(res) == ["실내박물관", "실내도서관", "야외공원"]
    park = res["result_cards"][2]
    assert park["warnings"] == ["강수"] and park["is_bad_day"]
    assert res["result_cards"][0]["warnings"] == []
    assert res["result_cards"][0]["is_bad_day"] is False


def test_bad_day_is_evaluated_per_place_location():
    tour = [tp(1, "가까운야외", 5, type_="tourapi:12"), tp(2, "먼야외", 20, type_="tourapi:12"),
            tp(3, "실내", 25, type_="tourapi:14")]
    hot = {round(at_km(5), 3): {"precip_prob_max": 0, "temp_max": 35, "temp_min": 25}}
    prov, _ = make_providers(tour, weather=hot)
    res = run(prov)
    assert names(res) == ["먼야외", "실내", "가까운야외"]
    assert res["result_cards"][2]["warnings"] == ["폭염"]
    assert res["result_cards"][0]["warnings"] == []


def test_dust_bad_day_warns_outdoor_not_indoor():
    tour = [tp(1, "야외", 5, type_="tourapi:28"), tp(2, "실내", 10, type_="tourapi:14")]
    prov, _ = make_providers(tour, dust={round(at_km(5), 3): {"pm10_grade": "나쁨", "pm25_grade": "보통"},
                                         round(at_km(10), 3): {"pm10_grade": "나쁨", "pm25_grade": "보통"}})
    res = run(prov)
    assert names(res) == ["실내", "야외"]
    assert res["result_cards"][0]["warnings"] == [] and res["result_cards"][1]["warnings"] == ["미세먼지"]


def test_ambiguous_type_uses_llm_for_indoor_outdoor_but_rule_types_do_not():
    tour = [tp(1, "레포츠", 5, type_="tourapi:28"), tp(2, "박물관", 6, type_="tourapi:14")]
    prov, calls = make_providers(tour, io={"레포츠": "indoor"})
    res = run(prov)
    assert set(calls["io"]) == {"레포츠"}
    assert {c["name"]: c["indoor_outdoor"] for c in res["result_cards"]} == {"레포츠": "indoor", "박물관": "indoor"}


# ------------------------------------------------------------------ widening / shortage

def test_radius_widens_once_by_1_5x_when_fewer_than_5():
    # 30 months -> 61.54 km; widened -> 92.3 km
    tour = [tp(i, f"가까움{i}", 10 + i) for i in range(3)] + [tp(i + 10, f"먼곳{i}", 70 + i) for i in range(4)]
    prov, _ = make_providers(tour)
    res = run(prov)
    assert res["radius_expanded"]
    assert res["radius_km"] == pytest.approx(2 * 40 / 1.3 * 1.5)
    assert len(names(res)) == 5 and res["notice"] is None


def test_not_widened_when_five_found():
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    res = run(prov)
    assert not res["radius_expanded"] and res["radius_km"] == pytest.approx(2 * 40 / 1.3)


def test_still_short_after_widening_tells_user():
    tour = [tp(1, "하나", 10), tp(2, "둘", 20), tp(3, "너무멀다", 150)]
    prov, _ = make_providers(tour)
    res = run(prov)
    assert res["radius_expanded"] and names(res) == ["하나", "둘"]
    assert "2곳" in res["notice"]


def test_unsuitable_exclusion_counts_toward_shortage_and_widening():
    tour = [tp(i, f"장소{i}", 5 + i) for i in range(5)] + [tp(9, "원거리적합", 80)]
    prov, _ = make_providers(tour, suit={"장소0": "부적합"})
    res = run(prov)
    assert res["radius_expanded"] and "원거리적합" in names(res) and len(names(res)) == 5


def test_zero_results_gives_notice():
    prov, _ = make_providers([])
    res = run(prov)
    assert res["result_cards"] == [] and "0곳" in res["notice"]


# ------------------------------------------------------------------ graceful degradation

def test_one_api_failure_only_affects_its_own_items():
    tour = [tp(i, f"장소{i}", 5 + i) for i in range(5)]
    prov, _ = make_providers(tour)

    def boom(*a):
        raise RuntimeError("down")

    prov.weather = boom
    res = run(prov)
    assert len(names(res)) == 5
    c = res["result_cards"][0]
    assert c["weather"] == {"status": "정보를 불러오지 못함"}
    assert "kma" in c["failed_sources"]
    assert c["facility_count"] == 1 and c["age_suitability"] == "적합"


def test_tour_api_failure_still_returns_kakao_places():
    kakao = [kk(i, f"카카오{i}", 5 + i) for i in range(5)]
    prov, _ = make_providers((), kakao)

    def boom(*a):
        raise TimeoutError

    prov.tour_search = boom
    res = run(prov)
    assert len(names(res)) == 5 and "tourapi" in res["failed_sources"]


# ------------------------------------------------------------------ chat flow

def test_chat_flow_shows_progress_and_cards():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: date(2026, 11, 11)))
    tour = [tp(i, f"장소{i:02d}", 3 + i) for i in range(15)]
    prov, _ = make_providers(tour, sleep=0.05)
    view = recommendation_turn(graph, "t-flow", "30개월 아기랑 강남역에서 내일 오전 10시 갈게요", prov)
    assert view["status"] == "ready"
    assert view["elapsed_s"] >= 0
    assert len(view["result_cards"]) == 5
    assert len(view["messages"]) >= 3  # ready reply + progress messages
    assert any("찾고 있어요" in m for m in view["messages"])


def test_chat_flow_asks_back_without_running_recommendation():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: date(2026, 11, 11)))
    prov, calls = make_providers([tp(1, "장소", 5)])
    view = recommendation_turn(graph, "t-ask", "아기랑 나들이", prov)
    assert view["status"] == "ask" and "result_cards" not in view and calls["judged"] == []


def test_nap_flag_flows_into_radius_in_chat():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: date(2026, 11, 11)))
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    recommendation_turn(graph, "t-nap", "10개월 아기, 강남역에서 내일 오전 10시", prov)
    view = recommendation_turn(graph, "t-nap", "네", prov)
    assert view["status"] == "ready" and view["max_drive_hours"] == 2.0


# ------------------------------------------------------------------ drive-time check

from backend.agents.review import review_sources  # noqa: E402
from backend.core.constants import DRIVE_CONFIRMED, DRIVE_UNVERIFIED  # noqa: E402
from backend.supervisor.cards import build_card  # noqa: E402
from backend.supervisor.intent import SCOPE_ENVIRONMENT  # noqa: E402
from backend.supervisor.pipeline import _STORED_KEYS, build_pipeline, departure_time_for, run_pipeline  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402


def test_place_over_drive_limit_is_dropped_and_next_one_picked():
    # 30 months -> 120 min limit; 장소0 is close but a 150-minute drive
    prov, calls = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(6)], drive={5.0: 150})
    res = run(prov)
    assert "장소0" not in names(res) and len(names(res)) == 5
    assert all(c["drive"]["status"] == DRIVE_CONFIRMED for c in res["result_cards"])
    assert res["result_cards"][0]["drive"]["minutes"] == pytest.approx(6 * 60 / 45)
    assert len(calls["drive"]) == 6


def test_drive_check_failure_marks_place_unverified():
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)], drive={5.0: RuntimeError("down")})
    res = run(prov)
    card = res["result_cards"][names(res).index("장소0")]
    assert card["drive"]["status"] == DRIVE_UNVERIFIED and card["drive"]["minutes"] is None
    assert "kakao_navi" in res["failed_sources"]
    assert build_card(card)["drive"]["status"] == DRIVE_UNVERIFIED


def test_without_drive_provider_radius_picks_are_unverified():
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)], drive=False)
    res = run(prov)
    assert len(names(res)) == 5
    assert all(c["drive"]["status"] == DRIVE_UNVERIFIED for c in res["result_cards"])


def test_widened_places_need_a_confirmed_drive_time():
    # 70 km is outside the 61.5 km age radius: shown only with a confirmed drive time
    tour = [tp(i, f"가까움{i}", 10 + i) for i in range(3)] + [tp(i + 10, f"먼곳{i}", 70 + i) for i in range(4)]
    prov, _ = make_providers(tour, drive=False)
    res = run(prov)
    assert res["radius_expanded"] and sorted(names(res)) == ["가까움0", "가까움1", "가까움2"]
    assert "3곳" in res["notice"]


def test_drive_time_is_estimated_for_09_on_the_outing_date():
    prov, calls = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    res = recommend(prov, age_months=30, departure=DEP, outing_date="2099-05-02")
    assert {d.strftime("%Y-%m-%d %H:%M") for d in calls["departures"]} == {"2099-05-02 09:00"}
    assert res["result_cards"][0]["drive"]["departure_time"] == "2099-05-02T09:00"
    assert build_card(res["result_cards"][0])["drive"]["departure_time"] == "2099-05-02T09:00"


def test_departure_time_is_now_when_09_has_passed_today():
    kst = timezone(timedelta(hours=9))
    now = datetime(2026, 11, 12, 13, 20, 30, tzinfo=kst)
    assert departure_time_for("2026-11-12", now) == datetime(2026, 11, 12, 13, 21, tzinfo=kst)
    assert departure_time_for("2026-11-14", now) == datetime(2026, 11, 14, 9, 0, tzinfo=kst)


def test_date_change_rechecks_drive_times_but_preference_change_reuses_them():
    prov, calls = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    pipe = build_pipeline(prov)
    first = run_pipeline(pipe, scope="full", departure=DEP, age_months=30, outing_date="2099-05-02")
    stored = {k: first.get(k) for k in _STORED_KEYS}
    n = len(calls["drive"])
    run_pipeline(pipe, scope="rerank", departure=DEP, age_months=30, outing_date="2099-05-02", stored=stored)
    assert len(calls["drive"]) == n                      # same departure time: reused
    again = run_pipeline(pipe, scope=SCOPE_ENVIRONMENT, departure=DEP, age_months=30, outing_date="2099-05-03",
                         stored=stored)
    assert len(calls["drive"]) == n + 5                  # new date: future traffic differs, re-checked
    assert {c["drive"]["departure_time"] for c in again["result_cards"]} == {"2099-05-03T09:00"}


# ------------------------------------------------------------------ review sources

def test_review_sources_keep_only_web_links_and_at_most_three():
    reviews = [{"title": "a", "link": "javascript:alert(1)", "source": "blog"}] + [
        {"title": f"t{i}", "link": f"https://blog.naver.com/x/{i}", "source": "blog"} for i in range(5)]
    out = review_sources(reviews)
    assert [s["link"] for s in out] == [f"https://blog.naver.com/x/{i}" for i in range(3)]


def test_card_shows_review_sources_as_links():
    prov, _ = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    place = run(prov)["result_cards"][0]
    card = build_card({**place, "review_sources": [
        {"title": "  서울숲  아기랑 ", "link": "https://cafe.naver.com/a/1", "source": "cafe"},
        {"title": "x", "link": "data:text/html,hi", "source": "blog"},
        {"title": "", "link": "https://blog.naver.com/b/2", "source": "evil"},
    ]})
    assert card["review_sources"] == [
        {"title": "서울숲 아기랑", "link": "https://cafe.naver.com/a/1", "source": "cafe"},
        {"title": "https://blog.naver.com/b/2", "link": "https://blog.naver.com/b/2", "source": None},
    ]


def test_drive_time_uses_the_given_departure_time():
    prov, calls = make_providers([tp(i, f"장소{i}", 5 + i) for i in range(5)])
    recommend(prov, age_months=30, departure=DEP, outing_date="2099-05-02", departure_time="14:30")
    assert {d.strftime("%Y-%m-%d %H:%M") for d in calls["departures"]} == {"2099-05-02 14:30"}
