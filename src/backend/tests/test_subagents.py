"""Sub-graphs run on their own: place search, environment, reviews & suitability."""
import time

from backend.agents import environment, place, review
from backend.constants import FAIL, NO_DUST
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
