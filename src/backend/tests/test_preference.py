"""Preference matching (RAG): retriever, profiles, the preference sub-graph, reference
lookup, ranking/augmentation in the pipeline, and the supervisor flow."""
from collections import Counter
from datetime import date

import pytest

from backend.agent import Deps, build_graph, recommendation_turn
from backend.agents import preference
from backend.agents.candidates import place_key
from backend.supervisor.cards import build_card
from backend.supervisor.pipeline import NOTICE_NO_MATCH, recommend
from backend.retriever import Document, VectorStore, cosine, split_sentences
from backend.tests.test_recommendation import DATE, DEP, make_providers, tp

TODAY = date(2026, 11, 11)
VOCAB = ["물놀이", "조용", "숲", "동물", "모래", "박물관", "공룡", "실내"]


def fake_embed(texts):
    """Deterministic bag-of-words vectors: one dimension per VOCAB word."""
    return [[1.0 if w in t else 0.0 for w in VOCAB] for t in texts]


def _boom(*a):
    raise RuntimeError("down")


def with_preference(prov, *, embed=fake_embed, keyword=None):
    calls = Counter()

    def counted_embed(texts):
        calls["embed"] += 1
        return embed(texts)

    def counted_keyword(q, lat, lng, r):
        calls["keyword"] += 1
        calls[f"keyword:{q}"] += 1
        return (keyword or (lambda *a: []))(q, lat, lng, r)

    prov.embed = counted_embed if embed else None
    prov.keyword_search = counted_keyword if keyword is not None else None
    return calls


def places():
    return [
        tp(1, "가까운곳", 2, description="넓은 잔디밭이 있는 쉼터입니다."),
        tp(2, "공룡관", 3, description="공룡 화석을 전시한 박물관입니다."),
        tp(3, "숲속놀이터", 4, description="숲 속에서 모래 놀이를 할 수 있어요."),
        tp(4, "물놀이장", 9, description="아기 물놀이 시설이 있습니다. 여름에 인기가 많아요."),
        tp(5, "동물농장", 6, description="동물 먹이 주기 체험을 할 수 있습니다."),
        tp(6, "평범한곳", 5, description="주차장이 넓습니다."),
    ]


# ---------------------------------------------------------------- retriever

def test_split_sentences_and_cosine():
    assert split_sentences("물놀이 시설이 있습니다. 여름에 인기가 많아요!\n주차 가능") == [
        "물놀이 시설이 있습니다", "여름에 인기가 많아요!", "주차 가능"]
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0


def test_vector_store_search_by_owner():
    docs = [Document("a#0", "a", "물놀이", "description"), Document("a#1", "a", "주차", "facility"),
            Document("b#0", "b", "물놀이 시설", "description")]
    store = VectorStore.build(docs, fake_embed([d.text for d in docs]))
    q = fake_embed(["물놀이"])[0]
    assert [d.doc_id for d, _ in store.search(q, owner="a", k=1)] == ["a#0"]
    assert {d.owner for d, _ in store.search(q, k=3)} == {"a", "b"}
    with pytest.raises(ValueError):
        VectorStore.build(docs, [[1.0]])


# ---------------------------------------------------------------- profiles

def test_profile_docs_cover_place_facts_and_skip_failures():
    p = {"name": "물놀이장", "ids": {"tourapi": "T4"}, "types": ["tourapi:28"],
         "description": "아기 물놀이 시설이 있습니다. 주차 가능.", "indoor_outdoor": "outdoor",
         "facilities": {"nursing_room": {"status": "있음"}, "parking": {"status": "없음"}},
         "review_summary": ["물이 따뜻해요", "정보를 불러오지 못함"]}
    docs = preference.profile_docs(p)
    kinds = [d.kind for d in docs]
    assert kinds == ["category", "description", "description", "setting", "facility", "review"]
    assert docs[0].text == "물놀이장은(는) 레포츠 시설입니다"
    assert all(d.doc_id.startswith("tourapi:T4#") and d.owner == place_key(p) for d in docs)
    assert "정보를 불러오지 못함" not in [d.text for d in docs]


def test_profile_names_the_kind_of_a_park_filed_as_a_plain_tourist_spot():
    """Round 1 #4 (2nd run): TourAPI files 만석거공원 as a 관광지 only."""
    p = {"name": "만석거공원", "ids": {"tourapi": "T9"}, "types": ["tourapi:12"], "description": ""}
    texts = [d.text for d in preference.profile_docs(p)]
    assert texts[:2] == ["만석거공원은(는) 관광지입니다", "만석거공원은(는) 공원입니다"]


# ---------------------------------------------------------------- sub-graph

def _merged(p, **kw):
    return {"name": p["name"], "ids": {"tourapi": p["id"]}, "types": [p["type"]],
            "description": p.get("description", ""), "indoor_outdoor": "indoor",
            "facilities": {}, "review_summary": [], **kw}


def test_preference_graph_levels_and_evidence():
    prov, _ = make_providers()
    with_preference(prov)
    ps = [_merged(p) for p in places()]
    out = preference.run(preference.build_graph(prov), places=ps, preference_text="물놀이 할 수 있는 곳",
                         reference=None)
    assert out["status"] == "ok"
    water = out["matches"]["tourapi:T4"]
    assert water["level"] == "높음"
    assert water["evidence"][0]["doc_id"].startswith("tourapi:T4#")
    assert "물놀이" in water["evidence"][0]["text"]
    plain = out["matches"]["tourapi:T6"]
    assert plain["level"] == "낮음" and plain["evidence"] == []


def test_preference_graph_uses_reference_profile():
    prov, _ = make_providers()
    with_preference(prov)
    ps = [_merged(p) for p in places()]
    ref = {"name": "서울숲", "profile": ["서울숲은(는) 관광지입니다", "숲 속 산책로와 모래 놀이터가 있어요"]}
    out = preference.run(preference.build_graph(prov), places=ps, preference_text=None, reference=ref)
    assert out["matches"]["tourapi:T3"]["level"] == "높음"


def test_preference_graph_without_or_with_failing_embeddings():
    prov, _ = make_providers()
    ps = [_merged(p) for p in places()]
    with_preference(prov, embed=None)
    out = preference.run(preference.build_graph(prov), places=ps, preference_text="물놀이", reference=None)
    assert out["status"] == "unavailable" and out["matches"] == {}
    with_preference(prov, embed=_boom)
    out = preference.run(preference.build_graph(prov), places=ps, preference_text="물놀이", reference=None)
    assert out["status"] == "failed" and out["failed_sources"] == ["embedding"]
    out = preference.run(preference.build_graph(prov), places=ps, preference_text=None, reference=None)
    assert out["status"] == "skipped"


# ---------------------------------------------------------------- reference lookup

SEOULSOOP = {"id": "R1", "name": "서울숲", "type": "tourapi:12", "address": "서울 성동구",
             "description": "숲 속 산책로와 모래 놀이터가 있는 공원입니다.", "lat": 37.54, "lng": 127.04}


def test_resolve_reference_statuses():
    prov, _ = make_providers()
    assert preference.resolve_reference(prov, "서울숲")["status"] == "unavailable"

    with_preference(prov, keyword=lambda q, *a: [SEOULSOOP])
    ok = preference.resolve_reference(prov, "서울숲")
    assert ok["status"] == "ok" and ok["name"] == "서울숲"
    assert any("모래 놀이터" in s for s in ok["profile"])

    many = [SEOULSOOP, {**SEOULSOOP, "id": "R2", "name": "서울숲 공원 주차장"}]
    with_preference(prov, keyword=lambda q, *a: many)
    assert preference.resolve_reference(prov, "서울숲")["status"] == "ok"  # one exact name match

    # round 1 #4 (2nd run): TourAPI and Kakao both list 서울숲 at the same spot -> one place
    kakao_soop = {**SEOULSOOP, "id": "K1", "source": "kakao", "lat": 37.5444, "lng": 127.0374}
    with_preference(prov, keyword=lambda q, *a: [SEOULSOOP, kakao_soop])
    assert preference.resolve_reference(prov, "서울숲")["status"] == "ok"
    park = {**kakao_soop, "type": "kakao:PARK"}
    with_preference(prov, keyword=lambda q, *a: [SEOULSOOP, park])
    ok = preference.resolve_reference(prov, "서울숲")
    assert ok["profile"][0] == "서울숲은(는) 공원입니다"                 # the kind Kakao knew, first
    with_preference(prov, keyword=lambda q, *a: [SEOULSOOP])
    assert not any("관광지입니다" in s for s in preference.resolve_reference(prov, "서울숲")["profile"])
    far = {**kakao_soop, "lat": 35.1, "lng": 129.0}                    # same name, another city
    with_preference(prov, keyword=lambda q, *a: [SEOULSOOP, far])
    assert preference.resolve_reference(prov, "서울숲")["status"] == "ambiguous"

    two = [{**SEOULSOOP, "name": "어린이대공원 (서울)"}, {**SEOULSOOP, "name": "어린이대공원 (부산)"}]
    with_preference(prov, keyword=lambda q, *a: two)
    amb = preference.resolve_reference(prov, "어린이대공원")
    assert amb["status"] == "ambiguous" and len(amb["candidates"]) == 2

    with_preference(prov, keyword=lambda q, *a: [])
    assert preference.resolve_reference(prov, "없는곳")["status"] == "not_found"
    with_preference(prov, keyword=_boom)
    assert preference.resolve_reference(prov, "서울숲")["status"] == "failed"


# ---------------------------------------------------------------- pipeline ranking

def test_preference_ranks_after_safety_before_distance():
    prov, _ = make_providers(places())
    with_preference(prov)
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE, preference_text="물놀이")
    names = [c["name"] for c in res["result_cards"]]
    assert names[0] == "물놀이장"                      # farthest, but best preference match
    assert res["preference_status"] == "ok"
    card = build_card(res["result_cards"][0])
    assert card["preference_match"]["level"] == "높음"
    assert any("물놀이" in e["text"] for e in card["preference_match"]["evidence"])


@pytest.mark.parametrize("text,setting", [
    ("실내 위주로 가고 싶어요", "indoor"), ("비 와도 괜찮은 곳으로요", "indoor"), ("비가 오면 들어갈 수 있는 곳", "indoor"),
    ("야외에서 뛰어놀 수 있는 곳", "outdoor"), ("실내도 야외도 좋아요", None), ("조용한 곳", None), (None, None),
])
def test_wanted_setting(text, setting):
    assert preference.wanted_setting(text) == setting


def test_indoor_wish_puts_indoor_places_first_with_the_setting_as_evidence():
    """Round 1 #3 / #17 (2nd run): "실내 위주로" / "비 와도 괜찮은 곳" barely moved the order."""
    prov, _ = make_providers()
    with_preference(prov)
    indoor = {"공룡관", "평범한곳"}
    pool = [_merged(p, indoor_outdoor="indoor" if p["name"] in indoor else "outdoor") for p in places()]
    out = preference.run(preference.build_graph(prov), places=pool,
                         preference_text="비 와도 괜찮은 숲 같은 곳으로요", reference=None)
    by_name = {p["name"]: out["matches"][place_key(p)] for p in pool}
    for name in indoor:
        assert by_name[name]["level"] == "높음"
        assert by_name[name]["evidence"][0]["text"] == "실내 장소입니다"
    # "숲" matches 숲속놀이터 by similarity, but it is outdoor: at most 보통
    assert by_name["숲속놀이터"]["level"] == "보통"
    assert all(by_name[n]["level"] != "높음" for n in by_name if n not in indoor)


def test_places_of_the_reference_kind_are_high():
    """Round 1 #4 (2nd run): "서울숲 같은 곳" must bring parks up, whatever the similarity."""
    prov, _ = make_providers()
    with_preference(prov, embed=lambda texts: [[1.0, 0.0] for _ in texts[:-1]] + [[0.0, 1.0]])   # all unrelated
    pool = [_merged(tp(1, "만석거공원", 3)), _merged(tp(2, "광교수목원", 4)), _merged(tp(3, "정글대탐험", 2)),
            _merged(tp(4, "공원옆동물원", 5))]
    ref = {"name": "서울숲", "profile": ["서울숲은(는) 공원입니다"], "kinds": ["공원"]}
    out = preference.run(preference.build_graph(prov), places=pool, preference_text=None, reference=ref)
    level = {p["name"]: out["matches"][place_key(p)] for p in pool}
    assert level["만석거공원"]["level"] == "높음"
    assert level["만석거공원"]["evidence"][0]["text"] == "만석거공원은(는) 공원입니다"
    assert level["광교수목원"]["level"] == "높음"                 # 자연 공원 counts as a park
    assert level["정글대탐험"]["level"] == "낮음"
    assert level["공원옆동물원"]["level"] == "낮음"               # "공원" in its name only: a zoo


def test_matching_outdoor_place_held_back_by_rain_is_explained():
    """Round 1 #4 (2nd run): parks matched "서울숲 같은 곳" but a rainy day put indoor places first."""
    from backend.tests.test_recommendation import at_km
    kinds = ["동물원", "키즈카페", "박물관", "체험관", "도서관"]      # distinct kinds: no per-kind cap
    tour = [tp(i, f"실내{k}", 2 + i, type_="tourapi:14") for i, k in enumerate(kinds)]
    tour.append(tp(9, "숲공원", 3.5, type_="tourapi:12", description="숲 속 산책로가 있습니다."))
    rainy = {round(at_km(3.5), 3): {"forecast_source": "short_term", "precip_prob_max": 80, "temp_max": 15,
                                    "temp_min": 5}}
    prov, _ = make_providers(tour, weather=rainy, io={"숲공원": "outdoor"})
    with_preference(prov)
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE, preference_text="숲")
    assert "숲공원" not in [c["name"] for c in res["result_cards"]]
    assert "숲공원 등" in res["notice"] and "실내 장소를 먼저" in res["notice"]


def test_safety_still_beats_preference():
    prov, _ = make_providers(places(), suit={"물놀이장": "부적합"})
    with_preference(prov)
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE, preference_text="물놀이")
    assert "물놀이장" not in [c["name"] for c in res["result_cards"]]


def test_without_preference_order_is_unchanged():
    prov, _ = make_providers(places())
    calls = with_preference(prov)
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE)
    assert [c["name"] for c in res["result_cards"]][0] == "가까운곳"
    assert calls["embed"] == 0 and res["preference_status"] == "off"
    assert build_card(res["result_cards"][0])["preference_match"] is None


def test_keyword_search_adds_candidates_when_few_strong_matches():
    extra = tp(9, "키즈물놀이터", 7, description="실내 물놀이 공간이 있습니다.")
    prov, _ = make_providers(places())
    calls = with_preference(prov, keyword=lambda q, *a: [extra] if q == "물놀이" else [])
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE,
                    preference_text="물놀이", keywords=["물놀이"])
    names = [c["name"] for c in res["result_cards"]]
    assert calls["keyword:물놀이"] == 1
    assert set(names[:2]) == {"물놀이장", "키즈물놀이터"}


def test_embedding_failure_falls_back_with_notice():
    prov, _ = make_providers(places())
    with_preference(prov, embed=_boom)
    res = recommend(prov, age_months=30, departure=DEP, outing_date=DATE, preference_text="물놀이")
    assert res["preference_status"] == "failed" and NOTICE_NO_MATCH in res["notice"]
    assert len(res["result_cards"]) == 5 and "embedding" in res["failed_sources"]


# ---------------------------------------------------------------- supervisor flow

FIRST = "30개월 아기랑 강남역에서 내일 오전 10시에 갈게요"


@pytest.fixture
def chat():
    graph = build_graph(Deps(geocode=lambda q: [DEP], today=lambda: TODAY))

    def make(keyword=None):
        prov, _ = make_providers(places())
        pcalls = with_preference(prov, keyword=keyword)
        api = Counter()
        for name in ("tour_search", "kakao_search", "reviews", "weather"):
            fn = getattr(prov, name)

            def wrap(*a, _fn=fn, _n=name):
                api[_n] += 1
                return _fn(*a)

            setattr(prov, name, wrap)
        tid = f"p{id(prov)}"
        return (lambda msg: recommendation_turn(graph, tid, msg, prov)), pcalls, api

    return make


def test_preference_follow_up_reranks_with_embeddings_only(chat):
    say, pcalls, api = chat()
    first = say(FIRST)
    assert first["result_cards"][0]["name"] == "가까운곳" and pcalls["embed"] == 0
    api.clear()
    v = say("물놀이 할 수 있는 곳 위주로요")
    assert v["intent"] == "change_preference"
    assert v["result_cards"][0]["name"] == "물놀이장"
    assert pcalls["embed"] == 1 and sum(api.values()) == 0
    assert any("취향" in m for m in v["messages"])


def test_date_change_reuses_stored_matches(chat):
    say, pcalls, _ = chat()
    say(FIRST)
    say("물놀이 할 수 있는 곳 위주로요")
    pcalls.clear()
    v = say("모레 오전 10시로 바꿔줘")
    assert v["intent"] == "change_date" and v["result_cards"][0]["name"] == "물놀이장"
    assert pcalls["embed"] == 0


def test_similar_place_resolves_reference_and_matches(chat):
    say, pcalls, _ = chat(keyword=lambda q, lat, *a: [SEOULSOOP] if lat is None else [])
    say(FIRST)
    v = say("서울숲 좋았는데 비슷한 곳 있을까요?")
    assert v["intent"] == "similar_place" and v["reference_place"] == "서울숲"
    assert v["result_cards"][0]["name"] == "숲속놀이터"


def test_ambiguous_reference_asks_to_choose(chat):
    two = [{**SEOULSOOP, "id": "A", "name": "어린이대공원 (서울)"},
           {**SEOULSOOP, "id": "B", "name": "어린이대공원 (부산)", "description": "동물원이 있어요."}]
    say, _, _ = chat(keyword=lambda q, lat, *a: two if lat is None else [])
    say(FIRST)
    v = say("어린이대공원 같은 곳 추천해줘")
    assert v["status"] == "ask" and len(v["reference_candidates"]) == 2
    v = say("2")
    assert v["status"] == "ready" and v["intent"] == "similar_place"
    assert v["result_cards"][0]["name"] == "동물농장"


def test_unknown_reference_asks_again_then_can_be_skipped(chat):
    say, _, _ = chat(keyword=lambda *a: [])
    say(FIRST)
    v = say("우주정거장 같은 곳 추천해줘")
    assert v["status"] == "ask" and "찾지 못했어요" in v["reply"]
    v = say("없음")
    assert v["status"] == "ready" and v["reference_place"] is None
