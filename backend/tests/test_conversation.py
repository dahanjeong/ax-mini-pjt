from datetime import date

import pytest

from backend.app.conversation import Deps, build_graph, chat_turn

TODAY = date(2026, 11, 11)  # Wednesday; forecast range = TODAY .. TODAY+10

GANGNAM = {"name": "강남역 2호선", "address": "서울 강남구 역삼동", "lat": 37.4979, "lng": 127.0276}
PLACES = {
    "강남역": [GANGNAM],
    "시청": [
        {"name": "서울시청", "address": "서울 중구 태평로1가", "lat": 37.5663, "lng": 126.9779},
        {"name": "수원시청", "address": "경기 수원시 팔달구", "lat": 37.2636, "lng": 127.0286},
        {"name": "대전시청", "address": "대전 서구 둔산동", "lat": 36.3504, "lng": 127.3845},
    ],
}


def geocode(q):
    if q == "고장":
        raise RuntimeError("kakao down")
    return PLACES.get(q, [])


@pytest.fixture
def chat():
    graph = build_graph(Deps(geocode=geocode, today=lambda: TODAY))
    counter = {"n": 0}

    def make_thread():
        counter["n"] += 1
        tid = f"t{counter['n']}"
        return lambda msg: chat_turn(graph, tid, msg)

    return make_thread


def test_extracts_all_inputs_from_one_message(chat):
    say = chat()
    r = say("30개월 아기랑 강남역에서 출발해서 내일 나들이 가려고요")
    assert r["status"] == "ready"
    assert r["baby_age_months"] == 30
    assert r["departure_location"]["name"] == GANGNAM["name"]
    assert r["outing_date"] == "2026-11-12"
    assert r["travels_during_nap"] is None  # no nap question for >= 24


def test_asks_for_each_missing_input_in_turn(chat):
    say = chat()
    r = say("아기랑 나들이 가고 싶어요")
    assert r["status"] == "ask" and "baby_age_months" in r["missing_inputs"]
    r = say("30개월이에요")
    assert "departure_location" in r["missing_inputs"]
    r = say("강남역")
    assert r["missing_inputs"] == ["outing_date"]
    r = say("11월 15일")
    assert r["status"] == "ready" and r["outing_date"] == "2026-11-15"


def test_age_in_years_is_converted(chat):
    r = chat()("3살 아이, 강남역에서 모레 갈게요")
    assert r["baby_age_months"] == 36 and r["status"] == "ready"


@pytest.mark.parametrize("msg", ["80개월 아기", "73개월이에요", "-3개월", "10살 아이"])
def test_age_out_of_range_refused_and_asked_again(chat, msg):
    say = chat()
    r = say(msg + ", 강남역에서 내일")
    assert r["status"] == "ask"
    assert r["baby_age_months"] is None
    assert "0~72" in r["notice"]
    assert "baby_age_months" in r["missing_inputs"]
    r = say("30개월")  # recovers afterwards
    assert r["status"] == "ready"


def test_age_boundaries_accepted(chat):
    assert chat()("0개월 아기, 강남역에서 내일 낮잠 안 겹쳐")["baby_age_months"] == 0
    assert chat()("72개월, 강남역에서 내일")["status"] == "ready"


def test_non_numeric_age_refused(chat):
    say = chat()
    say("아기랑 나들이")
    r = say("잘 모르겠어요")
    assert r["status"] == "ask" and r["baby_age_months"] is None
    assert "숫자" in r["notice"]
    r = say("열두 개월")
    assert "숫자" in r["notice"]


def test_nap_question_asked_once_for_under_24_months(chat):
    say = chat()
    r = say("10개월 아기, 강남역에서 내일 갈 거예요")
    assert r["status"] == "ask" and r["missing_inputs"] == ["travels_during_nap"]
    assert "낮잠" in r["reply"]
    r = say("네, 낮잠 시간이랑 겹쳐요")
    assert r["status"] == "ready" and r["travels_during_nap"] is True


def test_nap_no_answer_and_not_asked_again(chat):
    say = chat()
    say("6개월 아기")
    r = say("아니요")  # answers nap
    assert r["travels_during_nap"] is False
    assert "departure_location" in r["missing_inputs"]
    r = say("강남역")
    assert "낮잠" not in r["reply"]


def test_nap_asked_right_after_age_before_other_inputs(chat):
    r = chat()("6개월 아기")
    assert r["missing_inputs"] == ["travels_during_nap"]


def test_nap_given_in_first_message_not_asked(chat):
    r = chat()("23개월 아기, 강남역에서 내일, 낮잠 시간에는 이동 안 해요")
    assert r["status"] == "ready" and r["travels_during_nap"] is False


def test_exactly_24_months_no_nap_question(chat):
    r = chat()("24개월 아기, 강남역에서 내일")
    assert r["status"] == "ready"


def test_departure_not_found_asks_again(chat):
    say = chat()
    r = say("30개월, 없는동네에서 내일")
    assert r["status"] == "ask" and "찾지 못" in r["notice"]
    assert r["missing_inputs"] == ["departure_location"]
    r = say("강남역")
    assert r["status"] == "ready"


def test_ambiguous_departure_shows_candidates_and_accepts_choice(chat):
    say = chat()
    r = say("30개월, 시청에서 내일")
    assert r["status"] == "ask"
    assert [c["name"] for c in r["candidates"]] == ["서울시청", "수원시청", "대전시청"]
    for c in r["candidates"]:
        assert c["name"] in r["reply"]
    r = say("2번")
    assert r["status"] == "ready"
    assert r["departure_location"]["name"] == "수원시청"


def test_ambiguous_departure_choice_by_name(chat):
    say = chat()
    say("30개월, 시청에서 내일")
    r = say("대전시청이요")
    assert r["status"] == "ready" and r["departure_location"]["name"] == "대전시청"


def test_geocode_failure_asks_again(chat):
    r = chat()("30개월, 고장에서 내일")
    assert r["status"] == "ask" and "departure_location" in r["missing_inputs"]


def test_past_date_refused(chat):
    say = chat()
    r = say("30개월, 강남역에서 11월 1일")
    assert r["status"] == "ask" and "지난 날짜" in r["notice"]
    assert r["outing_date"] is None and r["missing_inputs"] == ["outing_date"]
    r = say("어제")
    assert "지난 날짜" in r["notice"]
    r = say("내일")
    assert r["status"] == "ready"


def test_date_beyond_forecast_shows_range(chat):
    say = chat()
    r = say("30개월, 강남역에서 12월 25일")
    assert r["status"] == "ask"
    assert r["available_date_range"] == {"start": "2026-11-11", "end": "2026-11-21"}
    assert "2026-11-11" in r["reply"] and "2026-11-21" in r["reply"]
    assert r["outing_date"] is None
    r = say("2026-11-21")  # last day of range is allowed
    assert r["status"] == "ready"


def test_today_is_allowed(chat):
    assert chat()("30개월, 강남역에서 오늘")["status"] == "ready"


def test_unparseable_date_asked_again(chat):
    say = chat()
    say("30개월, 강남역에서 출발")
    r = say("언젠가요")
    assert r["status"] == "ask" and r["notice"] and r["missing_inputs"] == ["outing_date"]


def test_history_is_in_memory_per_thread(chat):
    a, b = chat(), chat()
    a("30개월")
    r = b("강남역")
    assert r["baby_age_months"] is None and "baby_age_months" in r["missing_inputs"]
