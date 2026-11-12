"""Supervisor: intent judgement and re-run scope for follow-up requests."""
from collections import Counter
from datetime import date

import pytest

from backend.agent import Deps, build_graph, recommendation_turn
from backend.supervisor.intent import (
    SCOPE_ENVIRONMENT, SCOPE_FULL, SCOPE_RERANK, classify_message, parse_preference,
    parse_reference, plan_scope,
)
from backend.tests.test_recommendation import DEP, make_providers, tp

TODAY = date(2026, 11, 11)
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
    graph = build_graph(Deps(geocode=lambda q: [PANGYO] if "판교" in q else [DEP], today=lambda: TODAY))
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


def test_preference_and_reference_rules():
    assert parse_reference("서울숲 좋았는데 비슷한 곳 추천해줘") == "서울숲"
    assert parse_reference("전에 갔던 국립어린이박물관 같은 곳") == "국립어린이박물관"
    assert parse_reference("조용한 곳") is None
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
