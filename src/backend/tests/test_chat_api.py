"""POST /chat through FastAPI, with fake services (no network)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.agent import Deps, build_graph
from backend.api.chat import ChatService, get_service
from backend.main import app
from backend.supervisor.cards import CARD_FIELDS
from backend.tests.test_recommendation import DEP, make_providers, tp

TODAY = date(2026, 11, 11)
CITY_HALLS = [{"name": "서울시청", "address": "서울 중구", "lat": 37.5663, "lng": 126.9779},
              {"name": "수원시청", "address": "경기 수원시", "lat": 37.2636, "lng": 127.0286}]


@pytest.fixture
def api():
    graph = build_graph(Deps(geocode=lambda q: CITY_HALLS if q == "시청" else [DEP], today=lambda: TODAY))
    prov, calls = make_providers([tp(i, f"장소{i}", 3 + i) for i in range(8)])
    app.dependency_overrides[get_service] = lambda: ChatService(graph, prov)
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def post(client, message, session_id=None):
    body = {"message": message} if session_id is None else {"message": message, "session_id": session_id}
    return client.post("/chat", json=body)


def test_ask_back_creates_a_session(api):
    client, calls = api
    r = post(client, "아기랑 나들이 갈래요")
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "ask" and v["session_id"] and v["intent"] == "ask"
    assert v["reply"] and v["messages"] == [v["reply"]]
    assert "baby_age_months" in v["missing_inputs"]
    assert v["result_cards"] is None and calls["judged"] == []


def test_conversation_continues_and_returns_cards(api):
    client, _ = api
    sid = post(client, "30개월 아기랑 나들이")
    sid = sid.json()["session_id"]
    v = post(client, "강남역에서 내일 갈게요", sid).json()
    assert v["session_id"] == sid and v["status"] == "ready" and v["intent"] == "new_search"
    assert v["baby_age_months"] == 30 and v["outing_date"] == "2026-11-12"
    assert len(v["result_cards"]) == 5
    assert all(set(c) == set(CARD_FIELDS) for c in v["result_cards"])
    assert v["max_drive_hours"] == 2.0 and v["radius_expanded"] is False
    assert v["preference_status"] == "off" and v["failed_sources"] == []
    assert any("찾고 있어요" in m for m in v["messages"])
    # follow-up in the same session
    v = post(client, "모레로 바꿔줘", sid).json()
    assert v["intent"] == "change_date" and len(v["result_cards"]) == 5


def test_sessions_are_independent(api):
    client, _ = api
    a = post(client, "30개월 아기랑 강남역에서 내일").json()
    b = post(client, "아기랑 나들이").json()
    assert a["session_id"] != b["session_id"]
    assert a["status"] == "ready" and b["status"] == "ask"


def test_ambiguous_departure_lists_candidates(api):
    client, _ = api
    v = post(client, "30개월 아기랑 시청에서 내일").json()
    assert v["status"] == "ask" and [c["name"] for c in v["candidates"]] == ["서울시청", "수원시청"]


def test_place_detail_has_no_new_cards(api):
    client, calls = api
    sid = post(client, "30개월 아기랑 강남역에서 내일").json()["session_id"]
    calls["judged"].clear()
    v = post(client, "2번째 곳 더 알려줘", sid).json()
    assert v["intent"] == "place_detail" and v["result_cards"] is None and calls["judged"] == []


@pytest.mark.parametrize("body", [{}, {"message": ""}, {"message": "   "}, {"message": "가" * 501},
                                  {"message": "hi", "session_id": "x" * 101}])
def test_invalid_requests_are_422(api, body):
    client, _ = api
    assert client.post("/chat", json=body).status_code == 422


def test_unexpected_errors_are_500_without_internals(api):
    client, _ = api

    class Broken:
        def turn(self, session_id, message):
            raise RuntimeError("secret-key-1234 leaked in a stack trace")

    app.dependency_overrides[get_service] = lambda: Broken()
    r = post(client, "아기랑 나들이")
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}
    assert "secret" not in r.text


def test_health_still_ok(api):
    client, _ = api
    assert client.get("/health").json() == {"status": "ok"}


def test_service_start_failure_is_a_json_500(monkeypatch):
    import backend.api.chat as chat_mod

    def no_keys():
        raise RuntimeError("KAKAO_KEY is not set")

    monkeypatch.setattr(chat_mod, "_service", None)
    monkeypatch.setattr("backend.integrations.factory.build_deps", no_keys)
    r = TestClient(app).post("/chat", json={"message": "아기랑 나들이"})
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}


def test_env_file_is_read_from_the_repository_root():
    from backend.core.config import ROOT
    assert (ROOT / "README.md").is_file() and (ROOT / "src" / "backend").is_dir()
