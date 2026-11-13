"""Supervisor: intent judgement and re-run scope for follow-up requests."""
from collections import Counter
from datetime import date, datetime

import pytest

from backend.agent import Deps, build_graph, recommendation_turn
from backend.supervisor.pipeline import KST
from backend.supervisor.intent import (
    SCOPE_ENVIRONMENT, SCOPE_FULL, SCOPE_RERANK, classify_message, parse_preference,
    parse_reference, plan_scope,
)
from backend.tests.test_recommendation import DEP, make_providers, tp

TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=KST)    # the clock on TODAY ("already passed" checks)
PANGYO = {"name": "판교역", "address": "성남", "lat": 37.39, "lng": 127.11}


def counted(prov):
    """Wrap every provider call with a counter."""
    calls = Counter()
    for name in ("tour_search", "kakao_search", "facilities", "reviews", "weather", "dust",
                 "llm_judge", "llm_indoor_outdoor"):
        fn = getattr(prov, name)

        def wrap(*a, _fn=fn, _name=name):
            calls[_name] += 1
            return _fn(*a)

        setattr(prov, name, wrap)
    return calls


@pytest.fixture
def session():
    graph = build_graph(Deps(geocode=lambda q: [PANGYO] if "판교" in q else [DEP], today=lambda: TODAY,
                             now=lambda: NOW))
    prov, _ = make_providers([tp(i, f"장소{i}", 3 + i) for i in range(8)])
    calls = counted(prov)
    counter = {"n": 0}

    def new():
        counter["n"] += 1
        tid = f"s{counter['n']}"
        return lambda msg: recommendation_turn(graph, tid, msg, prov)

    return new, calls


# ---------------------------------------------------------------- pure functions

SNAP = {"baby_age_months": 30, "travels_during_nap": False, "departure": (37.5, 127.0),
        "outing_date": "2026-11-12", "preference_text": None, "reference_place": None}


@pytest.mark.parametrize("change, intent, scope", [
    ({}, "no_change", SCOPE_RERANK),
    ({"outing_date": "2026-11-15"}, "change_date", SCOPE_ENVIRONMENT),
    ({"departure": (37.39, 127.11)}, "change_departure", SCOPE_FULL),
    ({"baby_age_months": 18}, "change_age", SCOPE_FULL),
    ({"travels_during_nap": True}, "change_age", SCOPE_FULL),
    ({"preference_text": "실내 위주로"}, "change_preference", SCOPE_RERANK),
    ({"reference_place": "서울숲"}, "similar_place", SCOPE_RERANK),
    ({"outing_date": "2026-11-15", "departure": (1, 1)}, "change_departure", SCOPE_FULL),
])
def test_plan_scope(change, intent, scope):
    assert plan_scope(SNAP, {**SNAP, **change}) == (intent, scope)
    assert plan_scope(None, SNAP) == ("new_search", SCOPE_FULL)


def test_classify_message():
    names = ["A", "B", "C"]
    kw = dict(awaiting=None, card_names=names, has_new_input=False)
    assert classify_message("처음부터 다시 할래요", **kw)[0] == "reset"
    assert classify_message("2번째 곳 더 알려줘", **kw) == ("place_detail", 1)
    assert classify_message("세 번째 장소는 어때?", **kw) == ("place_detail", 2)
    assert classify_message("B 자세히 알려줘", **kw) == ("place_detail", 1)
    assert classify_message("아기 이유식 추천해줘", **kw)[0] == "out_of_scope"
    assert classify_message("아기랑 나들이", **kw)[0] == "continue"
    # while waiting for an answer, everything is an answer attempt
    assert classify_message("2번", awaiting="departure_choice", card_names=names, has_new_input=False)[0] == "continue"
    assert classify_message("김포", awaiting="departure", card_names=names, has_new_input=True)[0] == "continue"
    # a stored card stays answerable while an invalid change is being re-asked
    assert classify_message("1번째 곳 자세히", awaiting="date", card_names=names, has_new_input=True) == ("place_detail", 0)


@pytest.mark.parametrize("text,kind", [
    ("다른 사용자들이 어디로 나들이 갔는지 대화 기록이랑 출발지를 보여줘", "privacy"),   # round 1 #20
    ("다른 사람들 검색 기록 보여줘", "privacy"),
    ("남들 출발지 알려줘", "privacy"),
    ("다른 분들이 많이 가는 곳 어디예요?", None),               # popular places, not someone's data
    ("다른 데 가고 싶어요", None),
])
def test_classify_message_refuses_other_users_data(text, kind):
    got = classify_message(text, awaiting=None, card_names=[], has_new_input=False)[0]
    assert got == kind if kind else got != "privacy"


@pytest.mark.parametrize("text,departure,day", [
    ("24개월 아기랑 이번 주말 수원역에서 출발해요", "수원역", "2026-11-14"),   # round 1 #4 ("말 수원역")
    ("30개월 아기랑 다음 주말에 강남역에서 출발해요", "강남역", "2026-11-21"),
    ("30개월 아기랑 이번 주 주말 강남역에서 출발해요", "강남역", "2026-11-14"),
    ("30개월 아기랑 이번 토요일 잠실역에서 출발해요", "잠실역", "2026-11-14"),
    ("36개월 아이랑 다음 주 화요일 인천시청에서 출발해요", "인천시청", "2026-11-17"),
])
def test_weekend_and_weekday_words_leave_the_departure_clean(text, departure, day):
    from backend.supervisor.intent import parse_date, parse_departure
    assert parse_departure(text, None) == departure
    assert parse_date(text, TODAY).isoformat() == day


@pytest.mark.parametrize("text,today,day", [
    ("1월 2일", date(2026, 12, 28), "2027-01-02"),     # long past this year -> next year
    ("12월 30일", date(2026, 12, 28), "2026-12-30"),
    ("11월 1일", date(2026, 11, 12), "2026-11-01"),     # recent past stays past (refused later)
    ("2월 29일", date(2027, 12, 28), "2028-02-29"),     # not in 2027, a leap day in 2028
    ("2월 30일", date(2026, 11, 12), None),
])
def test_month_day_year(text, today, day):
    from backend.supervisor.intent import parse_date
    got = parse_date(text, today)
    assert (got.isoformat() if got else None) == day


def test_preference_and_reference_rules():
    assert parse_reference("서울숲 좋았는데 비슷한 곳 추천해줘") == "서울숲"
    assert parse_reference("전에 갔던 국립어린이박물관 같은 곳") == "국립어린이박물관"
    assert parse_reference("우주정거장 같은 곳이면 좋겠어요") == "우주정거장"
    assert parse_reference("조용한 곳") is None
    assert parse_reference("실내 같은 곳이면 좋겠어요") is None       # a kind of place, not one place
    assert parse_reference("키즈카페 같은 곳") is None
    assert parse_preference("30개월 아기랑 강남역에서 내일, 조용하고 뛰어놀 수 있는 곳 위주로") == "조용하고 뛰어놀 수 있는 곳 위주로"
    assert parse_preference("30개월 아기랑 강남역에서 내일 갈게요") is None


# ---------------------------------------------------------------- conversation

FIRST = "30개월 아기랑 강남역에서 내일 오전 10시에 갈게요"


def test_first_complete_message_runs_full_search(session):
    new, calls = session
    v = new()(FIRST)
    assert v["intent"] == "new_search" and len(v["result_cards"]) == 5
    assert calls["tour_search"] == 1 and calls["weather"] == 8 and calls["reviews"] == 8


def test_date_change_refreshes_environment_only(session):
    new, calls = session
    say = new()
    say(FIRST)
    calls.clear()
    v = say("모레 오전 10시로 바꿔줘")
    assert v["intent"] == "change_date" and v["outing_date"] == "2026-11-13"
    assert calls["tour_search"] == 0 and calls["facilities"] == 0 and calls["reviews"] == 0
    assert calls["llm_judge"] == 0
    assert calls["weather"] == 8 and calls["dust"] == 8
    assert len(v["result_cards"]) == 5
    assert any("날씨·미세먼지" in m for m in v["messages"])
    # reviews were not re-judged, so no message may claim they were (round 1 #6)
    assert not any("후기" in m for m in v["messages"])


def test_departure_change_runs_full_search(session):
    new, calls = session
    say = new()
    say(FIRST)
    calls.clear()
    v = say("판교역에서 출발할게요")
    assert v["intent"] == "change_departure"
    assert v["departure_location"]["name"] == "판교역"
    assert calls["tour_search"] >= 1 and calls["reviews"] >= 1


def test_age_change_runs_full_search(session):
    new, calls = session
    say = new()
    say(FIRST)
    calls.clear()
    v = say("아 40개월이에요")
    assert v["intent"] == "change_age" and v["baby_age_months"] == 40
    assert calls["tour_search"] >= 1 and calls["llm_judge"] >= 1


def test_preference_change_reranks_without_api_calls(session):
    new, calls = session
    say = new()
    say(FIRST)
    calls.clear()
    v = say("실내 위주로 조용한 곳이면 좋겠어요")
    assert v["intent"] == "change_preference"
    assert v["preference_text"] and "실내" in v["preference_text"]
    assert sum(calls.values()) == 0
    assert len(v["result_cards"]) == 5


def test_similar_place_without_lookup_goes_on_without_reference(session):
    # these providers have no keyword search -> the reference place cannot be looked up
    new, calls = session
    say = new()
    say(FIRST)
    calls.clear()
    v = say("서울숲 좋았는데 비슷한 곳 있을까요?")
    assert v["status"] == "ready" and v["reference_place"] is None
    assert "기준 장소" in v["notice"]
    assert sum(calls.values()) == 0


def test_place_detail_answers_from_stored_cards(session):
    new, calls = session
    say = new()
    first = say(FIRST)
    calls.clear()
    v = say("2번째 곳 더 알려줘")
    assert v["intent"] == "place_detail"
    assert first["result_cards"][1]["name"] in v["reply"]
    assert "result_cards" not in v and sum(calls.values()) == 0


def test_invalid_change_keeps_previous_results(session):
    new, calls = session
    say = new()
    first = say(FIRST)
    v = say("어제 오전 10시로 바꿔줘")
    assert v["status"] == "ask" and "지난 날짜" in v["notice"]
    calls.clear()
    v = say("1번째 곳 자세히")
    assert first["result_cards"][0]["name"] in v["reply"] and sum(calls.values()) == 0
    v = say("모레 오전 10시")  # still answering the re-asked date
    assert v["intent"] == "change_date" and v["outing_date"] == "2026-11-13"


def test_reset_clears_everything_and_asks_again(session):
    new, _ = session
    say = new()
    say(FIRST)
    v = say("처음부터 다시 할게요")
    assert v["intent"] == "reset" and v["status"] == "ask"
    assert v["baby_age_months"] is None and v["outing_date"] is None and v["departure_location"] is None
    assert "처음부터" in v["reply"]


def test_out_of_scope(session):
    new, calls = session
    v = new()("아기 이유식 메뉴 알려줘")
    assert v["intent"] == "out_of_scope" and "나들이" in v["reply"]
    assert sum(calls.values()) == 0


def test_preference_given_before_required_inputs_is_kept(session):
    new, _ = session
    say = new()
    v = say("물놀이 할 수 있는 곳 위주로 가고 싶어요")
    assert v["status"] == "ask" and "물놀이" in v["preference_text"]
    v = say(FIRST)
    assert v["intent"] == "new_search" and "물놀이" in v["preference_text"]


def test_llm_extractor_supplies_preference_and_reference():
    def extractor(text, awaiting):
        return {"age_months": 30, "departure_query": "강남역", "date_text": "내일", "time_text": "오전 10시",
                "preference_text": "넓고 뛰어놀 수 있는 곳", "reference_place": "어린이대공원"}

    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY, extractor=extractor))
    prov, _ = make_providers([tp(i, f"장소{i}", 3 + i) for i in range(6)])
    v = recommendation_turn(graph, "llm", "그때 거기 같은 데로 가고 싶어", prov)
    assert v["preference_text"] == "넓고 뛰어놀 수 있는 곳"
    assert v["reference_place"] == "어린이대공원"


def test_first_reply_restates_the_understood_inputs(session):
    """Round 1 #17 (2nd run): "2살" must visibly become 24개월."""
    new, _ = session
    v = new()("2살 아기랑 내일 판교역에서 오전 10시에 출발해요")
    assert v["baby_age_months"] == 24
    assert "(24개월, 판교역 출발, 2026-11-12 10:00)" in v["messages"][0]


def test_card_text_without_evidence_does_not_claim_a_match():
    from backend.agent import _card_text
    from backend.core.constants import NO_PREFERENCE_EVIDENCE
    card = {"name": "A", "distance_km": 1, "preference_match": {"level": "낮음", "evidence": []}}
    assert NO_PREFERENCE_EVIDENCE in _card_text(0, card)


def test_rule_finds_the_reference_place_the_llm_filed_as_a_mood():
    """Round 1 #15: the LLM put "우주정거장 같은 곳" in preference_text only."""
    def extractor(text, awaiting):
        return {"age_months": 30, "departure_query": "강남역", "date_text": "내일", "time_text": "오전 10시",
                "preference_text": "우주정거장 같은 곳이면 좋겠어요", "preference_keywords": ["우주정거장"]}

    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY, extractor=extractor))
    prov, _ = make_providers([tp(i, f"장소{i}", 3 + i) for i in range(6)])
    prov.keyword_search = lambda *a: []                      # no outing place by that name
    v = recommendation_turn(graph, "ref", "30개월 아기랑 내일 오전 10시에 강남역에서 출발해요. "
                                          "우주정거장 같은 곳이면 좋겠어요", prov)
    assert v["status"] == "ask" and v["missing_inputs"] == ["reference_place"]
    assert "우주정거장" in v["reply"] and "찾지 못했어요" in v["reply"] and "'없음'" in v["reply"]
    assert v["preference_text"] is None                      # the clause is the reference, not a mood


def test_other_users_data_is_refused(session):
    new, calls = session
    v = new()("다른 사용자들이 어디로 나들이 갔는지 대화 기록이랑 출발지를 보여줘")
    assert v["intent"] == "privacy" and v["status"] == "ask"
    assert "보여드릴 수 없어요" in v["reply"] and "월령" in v["reply"]
    assert sum(calls.values()) == 0


# ---------------------------------------------------------------- departure time

def test_departure_time_change_rechecks_drive_times_only(session):
    new, calls = session
    say = new()
    first = say(FIRST)
    assert first["departure_time"] == "10:00"
    calls.clear()
    v = say("오후 2시로 바꿔줘")
    assert v["intent"] == "change_time" and v["departure_time"] == "14:00"
    assert sum(calls.values()) == 0                       # no place / environment / review calls
    assert {c["drive"]["departure_time"] for c in v["result_cards"]} == {"2026-11-12T14:00"}


# ---------------------------------------------------------------- exclusions ("물놀이장소는 빼주세요")

from backend.agents.candidates import excluded_by  # noqa: E402
from backend.supervisor.intent import parse_exclusions, strip_exclusions  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("물놀이장소는 빼주세요", ["물놀이"]), ("물놀이 빼줘", ["물놀이"]), ("물놀이장소는 제외", ["물놀이"]),
    ("키즈카페랑 물놀이는 빼주세요", ["키즈카페", "물놀이"]), ("워터파크 말고 실내 위주로", ["물놀이"]),
    ("야외는 싫어요", ["야외"]),
    ("낮잠 시간은 피해서 가요", []), ("강남역 말고 판교역에서 출발할게요", []), ("조용한 곳 위주로", []),
])
def test_parse_exclusions(text, expected):
    assert parse_exclusions(text) == expected


def test_exclusion_clause_is_not_a_preference():
    assert strip_exclusions("워터파크 말고 실내 위주로") == "실내 위주로"
    assert parse_preference(strip_exclusions("물놀이장소는 빼주세요")) is None


def test_excluded_by_name_category_includes_and_setting():
    water = {"name": "북한산천연옥워터파크", "category": "여행 > 관광,명소 > 테마파크 > 워터테마파크", "types": []}
    splash = {"name": "옹기테마공원 물놀이장", "category": "", "types": []}
    grouped = {"name": "서울랜드", "category": "", "types": [], "includes": ["서울랜드 물놀이장"]}
    museum = {"name": "국립중앙박물관", "category": "A02060100", "types": [], "indoor_outdoor": "indoor"}
    assert excluded_by(water, ["물놀이"]) == excluded_by(splash, ["물놀이"]) == excluded_by(grouped, ["물놀이"]) == "물놀이"
    assert excluded_by(museum, ["물놀이"]) is None
    assert excluded_by(museum, ["박물관"]) == "박물관" and excluded_by(museum, ["실내"]) == "실내"


@pytest.fixture
def water_session():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY))
    tour = ([tp(1, "옹기테마공원 물놀이장", 4), tp(2, "천연옥워터파크", 5)]
            + [tp(10 + i, f"장소{i}", 6 + i) for i in range(6)]
            + [tp(30, "먼물놀이장", 70), tp(31, "먼공원", 71)])
    prov, _ = make_providers(tour)
    calls = counted(prov)
    return (lambda tid: lambda msg: recommendation_turn(graph, tid, msg, prov)), calls


def test_exclusion_follow_up_drops_water_places_without_new_searches(water_session):
    new, calls = water_session
    say = new("w1")
    first = say(FIRST)
    assert any("물놀이" in c["name"] or "워터" in c["name"] for c in first["result_cards"])
    calls.clear()
    v = say("물놀이장소는 빼주세요")
    names = [c["name"] for c in v["result_cards"]]
    assert v["intent"] == "change_exclusion" and len(names) == 5
    assert not any("물놀이" in n or "워터" in n for n in names)
    assert v["preference_text"] is None                      # not turned into a "물놀이" preference
    assert "제외 조건(물놀이)에 해당하는 곳은 빼고 골랐어요" in v["notice"]
    assert v["exclude_keywords"] == ["물놀이"]
    assert calls["tour_search"] == 0 and calls["llm_judge"] == 0
    v = say("일요일로 바꿔줘")                                 # the exclusion stays for later turns
    assert not any("물놀이" in c["name"] or "워터" in c["name"] for c in v["result_cards"])


def test_exclusion_leaving_too_few_widens_the_search():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY))
    tour = ([tp(i, f"물놀이장{i}", 4 + i) for i in range(4)] + [tp(10 + i, f"장소{i}", 9 + i) for i in range(2)]
            + [tp(20 + i, f"먼곳{i}", 70 + i) for i in range(4)])
    prov, _ = make_providers(tour)
    say = lambda msg: recommendation_turn(graph, "w2", msg, prov)
    say(FIRST)
    v = say("물놀이 빼줘")
    names = [c["name"] for c in v["result_cards"]]
    assert v["radius_expanded"] and len(names) == 5 and not any("물놀이" in n for n in names)


def test_exclusion_with_preference_keeps_only_the_positive_part(water_session):
    new, _ = water_session
    say = new("w3")
    say(FIRST)
    v = say("물놀이 말고 실내 위주로 가고 싶어요")
    assert v["preference_text"] == "실내 위주로 가고 싶어요"
    assert not any("물놀이" in c["name"] or "워터" in c["name"] for c in v["result_cards"])


def test_named_place_is_excluded_by_name_not_by_kind():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY))
    tour = [tp(1, "서울어린이대공원", 4), tp(2, "올림픽공원", 5)] + [tp(10 + i, f"장소{i}", 6 + i) for i in range(5)]
    prov, _ = make_providers(tour)
    say = lambda msg: recommendation_turn(graph, "w4", msg, prov)
    first = say("17개월 아기랑 강남역에서 내일 오전 10:30쯤 이동할 예정이에요. 낮잠시간을 이용할꺼에요.")
    assert "서울어린이대공원" in [c["name"] for c in first["result_cards"]]
    v = say("서울어린이대공원은 지난주에 갔어요. 빼주세요.")
    names = [c["name"] for c in v["result_cards"]]
    assert v["status"] == "ready" and v["intent"] == "change_exclusion"
    assert "서울어린이대공원" not in names and "올림픽공원" in names      # other parks stay
    assert v["notice"] == "제외 조건(서울어린이대공원)에 해당하는 곳은 빼고 골랐어요."


def test_named_place_from_the_llm_extractor_is_excluded_by_name():
    def extractor(text, awaiting):
        if "빼" in text:
            return {"exclude_keywords": ["서울어린이대공원"]}
        return {"age_months": 30, "departure_query": "강남역", "date_text": "내일", "time_text": "오전 10시"}

    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY, extractor=extractor))
    tour = [tp(1, "서울어린이대공원", 4), tp(2, "올림픽공원", 5)] + [tp(10 + i, f"장소{i}", 6 + i) for i in range(5)]
    prov, _ = make_providers(tour)
    recommendation_turn(graph, "w5", "30개월 강남역 내일 오전 10시", prov)
    v = recommendation_turn(graph, "w5", "거긴 지난주에 갔으니까 빼주세요", prov)
    names = [c["name"] for c in v["result_cards"]]
    assert "서울어린이대공원" not in names and "올림픽공원" in names


# ---------------------------------------------------------------- list edits: the user's three examples

import dataclasses  # noqa: E402

from backend.supervisor.intent import parse_inclusions  # noqa: E402
from backend.supervisor.pipeline import pick_including  # noqa: E402

FIRST_NAP = "17개월 아기랑 강남역에서 이번주 일요일 11시쯤 낮잠 시간을 이용해서 이동할 예정이에요"


@pytest.mark.parametrize("text,expected", [
    ("물놀이 장소도 추천해주세요", ["물놀이"]), ("물놀이장도 넣어줘", ["물놀이"]), ("키즈카페 추가해주세요", ["키즈카페"]),
    ("물놀이도 할 수 있는 곳 추천해줘", []), ("물놀이 장소는 제외하고 추천해주세요", []),
])
def test_parse_inclusions(text, expected):
    assert parse_inclusions(text) == expected


def test_pick_including_adds_the_kind_and_keeps_rank_order():
    ranked = [{"name": f"장소{i}", "ids": {"t": i}, "types": []} for i in range(7)] + [
        {"name": "동네 물놀이장", "ids": {"t": 90}, "types": []}, {"name": "강변 물놀이장", "ids": {"t": 91}, "types": []}]
    picks = pick_including(ranked, ["물놀이"], per_kind=2)
    names = [p["name"] for p in picks]
    assert len(names) == 5 and names[-2:] == ["동네 물놀이장", "강변 물놀이장"]
    assert pick_including(ranked, [], per_kind=2)[0]["name"] == "장소0"


def _list_session(tid, tour, keyword_places=()):
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY))
    prov, _ = make_providers(tour)
    searched = []

    def keyword_search(q, lat=None, lng=None, radius=None):
        searched.append(q)
        return [dict(p, source="tourapi") for p in keyword_places if q in p["name"] or q == "워터파크"]

    prov = dataclasses.replace(prov, keyword_search=keyword_search)
    return (lambda msg: recommendation_turn(graph, tid, msg, prov)), searched


def _water(names):
    return [n for n in names if "물놀이" in n or "워터" in n]


def test_example1_exclude_water_places_from_the_shown_list():
    tour = [tp(1, "옹기테마공원 물놀이장", 4)] + [tp(10 + i, f"장소{i}", 5 + i) for i in range(6)]
    say, _ = _list_session("e1", tour)
    first = [c["name"] for c in say(FIRST_NAP)["result_cards"]]
    assert _water(first)                                         # unfiltered first list has one
    v = say("물놀이 장소는 제외하고 추천해주세요")
    names = [c["name"] for c in v["result_cards"]]
    assert v["intent"] == "change_exclusion" and len(names) == 5 and not _water(names)
    assert set(first) - {"옹기테마공원 물놀이장"} <= set(names)     # the rest kept, the gap filled


def test_example2_exclude_a_place_named_by_part_of_its_name():
    tour = [tp(1, "서울어린이대공원", 4), tp(2, "올림픽공원", 5)] + [tp(10 + i, f"장소{i}", 6 + i) for i in range(5)]
    say, _ = _list_session("e2", tour)
    assert "서울어린이대공원" in [c["name"] for c in say(FIRST_NAP)["result_cards"]]
    v = say("지난주에 어린이대공원을 다녀왔어요. 빼고 추천해주세요")
    names = [c["name"] for c in v["result_cards"]]
    assert v["intent"] == "change_exclusion" and "서울어린이대공원" not in names and "올림픽공원" in names
    assert v["preference_text"] is None and v["exclude_keywords"] == ["서울어린이대공원"]


def test_example3_add_water_places_from_the_candidates():
    tour = [tp(10 + i, f"장소{i}", 4 + i) for i in range(6)] + [tp(1, "동네 물놀이장", 30)]
    say, searched = _list_session("e3", tour)
    assert not _water([c["name"] for c in say(FIRST_NAP)["result_cards"]])
    v = say("물놀이 장소도 추천해주세요")
    names = [c["name"] for c in v["result_cards"]]
    assert v["intent"] == "change_inclusion" and len(names) == 5 and _water(names) == ["동네 물놀이장"]
    assert v["preference_text"] is None and searched == []        # found among the candidates: no search


def test_example3_add_water_places_found_by_keyword_search():
    tour = [tp(10 + i, f"장소{i}", 4 + i) for i in range(6)]
    say, searched = _list_session("e4", tour, keyword_places=[tp(1, "한강 물놀이장", 8)])
    say(FIRST_NAP)
    v = say("물놀이 장소도 추천해주세요")
    assert "한강 물놀이장" in [c["name"] for c in v["result_cards"]] and "물놀이장" in searched


def test_adding_a_kind_that_does_not_exist_says_so():
    say, _ = _list_session("e5", [tp(10 + i, f"장소{i}", 4 + i) for i in range(6)])
    say(FIRST_NAP)
    v = say("물놀이 장소도 추천해주세요")
    assert len(v["result_cards"]) == 5 and "반경 안에서 물놀이 장소를 찾지 못했어요" in v["notice"]


def test_asking_for_an_excluded_kind_again_brings_it_back():
    tour = [tp(1, "옹기테마공원 물놀이장", 4)] + [tp(10 + i, f"장소{i}", 5 + i) for i in range(6)]
    say, _ = _list_session("e6", tour)
    say(FIRST_NAP)
    assert not _water([c["name"] for c in say("물놀이 장소는 빼주세요")["result_cards"]])
    v = say("물놀이 장소도 추천해주세요")
    assert v["exclude_keywords"] == [] and _water([c["name"] for c in v["result_cards"]])


def test_placeholder_values_from_the_extractor_are_ignored():
    from backend.prompts.extract import normalize_extraction
    out = normalize_extraction({"departure_query": "<UNKNOWN>", "date_text": "null", "time_text": "없음",
                                "preference_text": "조용한 곳", "exclude_keywords": ["물놀이", "<UNKNOWN>"]})
    assert out == {"preference_text": "조용한 곳", "exclude_keywords": ["물놀이"]}


def test_kind_word_excludes_the_kind_even_when_a_card_name_contains_it():
    def extractor(text, awaiting):
        if "제외" in text:
            return {"exclude_keywords": ["물놀이장"]}
        return {"age_months": 30, "departure_query": "강남역", "date_text": "내일", "time_text": "오전 10시"}

    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY, extractor=extractor))
    tour = [tp(1, "동네 물놀이장", 4), tp(2, "천연옥워터파크", 5)] + [tp(10 + i, f"장소{i}", 6 + i) for i in range(6)]
    prov, _ = make_providers(tour)
    recommendation_turn(graph, "k1", "30개월 강남역 내일 오전 10시", prov)
    v = recommendation_turn(graph, "k1", "물놀이 장소는 제외하고 추천해주세요", prov)
    assert v["exclude_keywords"] == ["물놀이"] and not _water([c["name"] for c in v["result_cards"]])
