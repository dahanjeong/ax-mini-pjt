"""Sub-graphs run on their own: place search, environment, reviews & suitability."""
import time

from backend.agents import candidates, environment, place, review
from backend.core.constants import FAIL, NO_DUST
from backend.tests.test_recommendation import DATE, DEP, FAC_ALL, GOOD_D, GOOD_W, kk, make_providers, tp


def _boom(*a):
    raise RuntimeError("down")


# ---------------------------------------------------------------- place

def test_place_graph_fans_out_facility_lookup_per_candidate():
    prov, _ = make_providers(tour=[tp(1, "A", 3), tp(2, "B", 5)], fac={"A": FAC_ALL})
    out = place.run(place.build_graph(prov), departure=DEP, age_months=30, travels_during_nap=False)
    assert [c["name"] for c in out["candidates"]] == ["A", "B"]
    a, b = out["candidates"]
    assert a["public_facilities"] == FAC_ALL and a["public_failed_sources"] == []
    assert b["public_facilities"]["nursing_room"] == "있음"  # FAC_ONE default
    assert out["max_drive_hours"] == 2.0
    assert out["failed_sources"] == []


def test_place_graph_facility_lookups_run_in_parallel():
    cands = [tp(i, f"P{i}", 1 + i) for i in range(8)]
    prov, _ = make_providers(tour=cands, sleep=0.3)
    t0 = time.monotonic()
    out = place.run(place.build_graph(prov), departure=DEP, age_months=30, travels_during_nap=False)
    assert len(out["candidates"]) == 8
    assert time.monotonic() - t0 < 8 * 0.3  # not sequential


def test_place_graph_marks_only_failed_facility_lookup():
    prov, _ = make_providers(tour=[tp(1, "A", 3)])
    prov.facilities = _boom
    out = place.run(place.build_graph(prov), departure=DEP, age_months=30, travels_during_nap=False)
    (a,) = out["candidates"]
    assert a["public_facilities"] is None
    assert a["public_failed_sources"] == ["public_data"]
    assert out["failed_sources"] == []  # collection itself succeeded


def test_place_graph_without_candidates_and_widened_radius():
    prov, _ = make_providers()
    g = place.build_graph(prov)
    base = place.run(g, departure=DEP, age_months=10, travels_during_nap=False)
    wide = place.run(g, departure=DEP, age_months=10, travels_during_nap=False, radius_scale=place.WIDEN_FACTOR)
    assert base["candidates"] == []
    assert wide["radius_km"] == base["radius_km"] * place.WIDEN_FACTOR


def test_place_graph_records_collection_failure():
    prov, _ = make_providers(kakao=[kk(1, "K", 2)])
    prov.tour_search = _boom
    out = place.run(place.build_graph(prov), departure=DEP, age_months=30, travels_during_nap=False)
    assert out["failed_sources"] == ["tourapi"]
    assert [c["name"] for c in out["candidates"]] == ["K"]


# ---------------------------------------------------------------- environment

P = {"name": "A", "lat": 37.52, "lng": 127.0, "types": ["tourapi:12"]}


def test_environment_graph_good_day():
    prov, _ = make_providers()
    out = environment.run(environment.build_graph(prov), place=P, date=DATE)
    assert out["weather"] == GOOD_W and out["dust"] == GOOD_D
    assert out["is_bad_day"] is False and out["bad_day_warnings"] == []
    assert out["failed_sources"] == []


def test_environment_graph_weather_failure_and_missing_dust():
    prov, _ = make_providers()
    prov.weather = _boom
    prov.dust = lambda *a: {}
    out = environment.run(environment.build_graph(prov), place=P, date=DATE)
    assert out["weather"] == {"status": FAIL}
    assert out["dust"] == {"status": NO_DUST}
    assert out["failed_sources"] == ["kma"]


def test_environment_graph_runs_weather_and_dust_in_parallel():
    prov, _ = make_providers(sleep=0.4)
    t0 = time.monotonic()
    environment.run(environment.build_graph(prov), place=P, date=DATE)
    assert time.monotonic() - t0 < 0.75


# ---------------------------------------------------------------- review

def test_review_graph_rule_decides_indoor_without_llm():
    prov, calls = make_providers()
    out = review.run(review.build_graph(prov), place={**P, "types": ["tourapi:14"]}, age_months=20)
    assert out["indoor_outdoor"] == "indoor"
    assert calls["io"] == []
    assert out["age_suitability"] == "적합"
    assert out["review_summary"] == ["좋아요", "넓어요", "깨끗해요"]
    assert out["review_evidence_count"] == 5 and out["mentions_failed"] is False


def test_review_graph_asks_llm_when_category_is_ambiguous():
    prov, calls = make_providers(io={"A": "indoor"})
    out = review.run(review.build_graph(prov), place=P, age_months=20)
    assert calls["io"] == ["A"]
    assert out["indoor_outdoor"] == "indoor"


def test_review_graph_review_failure():
    prov, _ = make_providers()
    prov.reviews = _boom
    out = review.run(review.build_graph(prov), place=P, age_months=20)
    assert out["review_summary"] == [FAIL]
    assert out["mentions_failed"] is True
    assert "naver" in out["failed_sources"]


# ---------------------------------------------------------------- preselection

def cand(name, km, cat="", types=("tourapi:12",), image=False):
    return {"name": name, "distance_km": km, "category": cat, "types": list(types), "has_image": image}


def test_kind_tier():
    assert candidates.kind_tier(cand("서울대공원", 10, "A02020600")) == 1             # 테마공원 (TourAPI code)
    assert candidates.kind_tier(cand("국립과천과학관", 20, "A02060300")) == 1          # 과학관 by name
    assert candidates.kind_tier(cand("키즈랜드", 1, "음식점 > 카페 > 테마카페 > 키즈카페", ("kakao:KIDS",))) == 3  # everyday
    assert candidates.kind_tier(cand("어린이박물관", 3, "A02060100")) == 1             # 어린이 in name
    assert candidates.kind_tier(cand("국립중앙박물관", 8, "A02060100")) == 2
    assert candidates.kind_tier(cand("올림픽공원", 9, "여행 > 공원")) == 2
    assert candidates.kind_tier(cand("역삼까치공원", 0.3, "여행 > 공원 > 도시근린공원")) == 3   # small park
    assert candidates.kind_tier(cand("까치어린이공원", 0.5, "여행 > 공원")) == 3               # not tier 1
    assert candidates.kind_tier(cand("유나갤러리", 0.2, "문화,예술 > 문화시설 > 미술관")) == 3
    assert candidates.kind_tier(cand("동네도서관", 2, "A02060900")) == 3


def test_preselect_spreads_bands_and_prefers_better_kinds():
    near = [cand(f"갤러리{i}", 0.1 * i + 0.1, "A02060500") for i in range(10)]
    near += [cand("과학관", 4.0, "A02060300")]
    mid = [cand(f"공원{i}", 6 + i, "A02020700") for i in range(8)] + [cand("수목원", 19, "A01010700")]
    far = [cand(f"도서관{i}", 21 + i, "A02060900") for i in range(3)] + [cand("테마파크", 40, "A02020600")]
    picked = candidates.preselect(near + mid + far, radius=46.2, n=15)
    names = [p["name"] for p in picked]
    assert len(picked) == 15 and [p["distance_km"] for p in picked] == sorted(p["distance_km"] for p in picked)
    assert {"과학관", "수목원", "테마파크"} <= set(names)                  # tier 1 wins inside each band
    assert sum(p["distance_km"] < 5 for p in picked) == 5                 # equal share per band
    assert sum(p["distance_km"] >= 20 for p in picked) == 4               # band has only 4 -> rest refilled
    assert sum(5 <= p["distance_km"] < 20 for p in picked) == 6


def test_preselect_small_radius_and_image_tiebreak():
    ps = [cand("A", 1, "A02020700"), cand("B", 2, "A02020700", image=True), cand("C", 7, "A02020700")]
    picked = candidates.preselect(ps, radius=8, n=2)                          # bands 0-5, 5-8
    assert [p["name"] for p in picked] == ["B", "C"]                      # B: same tier, has an image
    assert candidates.preselect([], radius=30) == []


# ---------------------------------------------------------------- one facility, many entries

def ent(name, lat, src="kakao", km=5.0):
    return {"name": name, "lat": lat, "lng": 127.0, "place_source": [src], "distance_km": km}


def test_same_facility():
    assert candidates.same_facility(ent("서울대공원", 37.43), ent("서울대공원 제1아프리카관", 37.432))
    assert candidates.same_facility(ent("서울어린이대공원 동물원", 37.55), ent("서울어린이대공원 놀이동산", 37.551))
    assert not candidates.same_facility(ent("어린이대공원", 37.55), ent("어린이도서관", 37.55))      # shared 3 chars
    assert not candidates.same_facility(ent("서울대공원", 37.43), ent("서울대공원 주차장", 37.46))    # 3 km apart
    assert not candidates.same_facility(ent("국립중앙박물관", 37.52), ent("국립국악원", 37.52))       # "국립" is not a word


def test_group_facilities_prefers_the_plain_facility_entry():
    ps = [ent("서울대공원 어린이동물원", 37.430, km=7.8), ent("서울대공원 제1아프리카관", 37.431, km=7.9),
          ent("서울대공원", 37.4305, src="tourapi", km=8.0), ent("과천과학관", 37.44, km=9.0)]
    out = candidates.group_facilities(ps)
    assert [g["name"] for g in out] == ["서울대공원", "과천과학관"]
    assert sorted(out[0]["includes"]) == ["서울대공원 어린이동물원", "서울대공원 제1아프리카관"]
    assert out[1]["includes"] == []


# ---------------------------------------------------------------- family-outing ranking

def test_outing_grade_and_kind():
    g = candidates.outing_grade
    assert g(cand("서울어린이대공원 동물원", 7, "여행 > 관광,명소 > 동물원")) == "A"
    assert g(cand("파주 율곡습지공원", 40, "A02020700")) == "A"
    assert g(cand("관광농원", 30, "A02030100")) == "A"                     # 농.산.어촌 체험
    assert g(cand("국립중앙박물관", 8, "A02060100")) == "B"
    assert g(cand("용인 구갈레스피아", 27, "A02020700")) == "B"             # park
    assert g(cand("헬로방방", 1, "음식점 > 카페 > 테마카페 > 키즈카페", ("kakao:KIDS",))) == "C"
    assert g(cand("동네도서관", 2, "A02060900")) == "C"
    assert g(cand("역삼까치공원", 0.3, "여행 > 공원 > 도시근린공원")) == "C"
    k = candidates.kind_of
    assert k(cand("서울어린이대공원 동물원", 7, "여행 > 관광,명소 > 동물원")) == "zoo"
    assert k(cand("헬로방방", 1, "", ("kakao:KIDS",))) == "kids"
    assert k(cand("국립과천과학관", 20, "A02060300")) == "museum"
    assert k(cand("무명", 3, "")) == "other"


def ranked_place(name, km, cat="", suit="적합", fac=0, io="indoor", bad=False, types=("tourapi:12",), match=None):
    return {"name": name, "distance_km": km, "category": cat, "types": list(types), "age_suitability": suit,
            "facility_count": fac, "indoor_outdoor": io, "is_bad_day": bad, "preference_match": match}


def test_rank_places_family_outing_order():
    from backend.supervisor.pipeline import rank_places
    ps = [ranked_place("키즈카페", 0.9, "음식점 > 카페 > 테마카페 > 키즈카페", fac=3, types=("kakao:KIDS",)),
          ranked_place("박물관", 8, "A02060100", fac=3),
          ranked_place("동물원(보통)", 20, "여행 > 관광,명소 > 동물원", suit="보통"),
          ranked_place("동물원(적합)", 30, "여행 > 관광,명소 > 동물원")]
    assert [p["name"] for p in rank_places(ps)] == ["동물원(적합)", "동물원(보통)", "박물관", "키즈카페"]
    # a bad day pushes outdoor destinations behind indoor ones
    ps[3]["io"] = ps[3]["indoor_outdoor"] = "outdoor"
    ps[3]["is_bad_day"] = True
    assert rank_places(ps)[-1]["name"] == "동물원(적합)"
    # a preference match beats the outing grade
    ps[0]["preference_match"] = {"level": "높음"}
    for p in ps[1:]:
        p["preference_match"] = {"level": "낮음"}
    assert rank_places(ps)[0]["name"] == "키즈카페"


def test_pick_varied_caps_each_kind_at_two():
    from backend.supervisor.pipeline import pick_varied
    kids = [ranked_place(f"키즈{i}", i, types=("kakao:KIDS",)) for i in range(4)]
    zoo = [ranked_place("동물원", 9, "동물원")]
    museum = [ranked_place("박물관", 10, "A02060100")]
    picked = pick_varied(kids + zoo + museum, n=5)
    assert [p["name"] for p in picked] == ["키즈0", "키즈1", "동물원", "박물관", "키즈2"]
    assert [p["name"] for p in pick_varied(kids, n=3)] == ["키즈0", "키즈1", "키즈2"]   # nothing else to use


def test_group_facilities_without_plain_entry_shows_the_shared_name():
    ps = [ent("서울대공원 산림욕장", 37.430, src="tourapi", km=7.9),
          ent("서울대공원 어린이동물원", 37.431, km=7.8)]
    (g,) = candidates.group_facilities(ps)
    assert g["name"] == "서울대공원"
    assert g["includes"] == ["서울대공원 어린이동물원", "서울대공원 산림욕장"]
    assert g["lat"] == 37.431          # location / ids of the best outing part (the children's zoo)


def test_group_facilities_chains_members():
    # b is within 1 km of a and of c, while a and c are 1.6 km apart: one facility
    ps = [ent("올림픽공원 장미광장", 37.520, km=1), ent("올림픽공원 평화의문", 37.527, km=2),
          ent("올림픽공원 몽촌토성", 37.5345, km=3)]
    assert len(candidates.group_facilities(ps)) == 1
